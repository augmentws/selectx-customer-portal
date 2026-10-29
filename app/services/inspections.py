"""GoCanvas inspections: import form definitions and parse submissions into typed rows.

A submission is a flat list of responses with no zones, so the form definition supplies them:
each GoCanvas section that asks "Has this zone been inspected?" is a zone, and each entry is
mapped to a field by its label. Every response is also stored as received.

Values are typed leniently. GoCanvas keeps the form id across versions, and older submissions
use options and formats the current form doesn't (quantities in Material Use, "3" for
"RAMP 3", multi-selects joined by newlines or commas). Anything that can't be typed is left
null in the typed tables and recorded in `parse_warnings`; it is never dropped.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    InspectionForm,
    InspectionFormField,
    InspectionFormZone,
    InspectionKind,
    InspectionPhoto,
    InspectionPhotoValue,
    InspectionResponse,
    InspectionSubmission,
    Location,
    RiskInspectionMaterial,
    RiskInspectionSummary,
    RiskInspectionZone,
    ServiceOrder,
)
from app.services import files


class InspectionError(Exception):
    """A submission that can't be stored (its form isn't imported, or it isn't a submission)."""


# Label prefixes (normalized: lowercase, punctuation and repeated spaces removed) to field keys.
# Order matters: the first match wins, so longer prefixes come before shorter ones.
HEADER_FIELDS = [
    ("inspector name", "inspector_name"),
    ("new date", "date"),
    ("new time", "time"),
    ("store number", "store"),
    ("address", "address"),
    ("city", "city"),
    ("work order id", "work_order_ref"),
]
SUMMARY_FIELDS = [
    ("ramp recommendation", "ramp_recommendation"),
    ("service manager summary", "manager_summary"),
    ("notes on material use", "material_notes"),
]
ZONE_FIELDS = [
    ("has this zone been inspected", "inspected"),
    ("all checked", "all_areas_inspected"),
    ("mark all areas", "areas"),
    ("check all areas", "areas"),
    ("check all that apply to location", "areas"),
    ("are doors properly aligned", "doors_aligned"),
    ("are door sweeps", "door_sweeps_ok"),
    ("are doors", "doors_are"),
    ("evidence of rodent", "rodent_activity"),
    ("evidence of pest", "pest_activity"),
    ("type of pest", "pest_types"),
    ("provide any additional notes", "additional_notes"),
    ("provide any additional necessary images", "photos_additional"),
    ("notes on pest", "pest_notes"),
    ("images of pest", "photos_pest"),
    ("sanitation risk", "sanitation_risk"),
    ("notes on sanitation", "sanitation_notes"),
    ("images of sanitation", "photos_sanitation"),
    ("structural integrity risk", "structural_risk"),
    ("notes on structural", "structural_notes"),
    ("images of structural", "photos_structural"),
    ("overall risk", "overall_risk"),
    # Zone-specific questions, kept in `attributes`.
    ("is dumpster", "attr.dumpster"),
    ("is trash room", "attr.trash_room"),
    ("is basement", "attr.basement"),
    ("is ceiling", "attr.ceiling"),
    ("is exterior perimeter", "attr.exterior_perimeter"),
    ("is paneling", "attr.paneling"),
    ("is location in a mall", "attr.in_mall"),
    ("mall", "attr.mall"),
    ("is dumbwaiter operational", "attr.dumbwaiter_operational"),
]
# Pest types the form spells differently from zone to zone, mapped to one spelling.
PEST_TYPE_ALIASES = {"occasional invader": "Occasional Invaders"}
# Attributes answered Yes/No; the rest are option lists.
BOOLEAN_ATTRIBUTES = {"in_mall", "dumbwaiter_operational"}
MATERIAL_PREFIX = "material."
INSPECTED_QUESTION = "has this zone been inspected"


def _normalize(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ ]+", " ", label.lower())).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _match(label: str, rules: list[tuple[str, str]]) -> str | None:
    normalized = _normalize(label)
    return next((key for prefix, key in rules if normalized.startswith(prefix)), None)


def _entries(definition: dict):
    for section in definition.get("sections") or []:
        for sheet in section.get("sheets") or []:
            for entry in sheet.get("entries") or []:
                yield section, entry


# --- Forms ------------------------------------------------------------------------------------


def import_form(
    db: Session, operator_id: uuid.UUID, definition: dict, kind: InspectionKind
) -> InspectionForm:
    """Store a GoCanvas form definition and derive its zones and field map. Re-importing the
    same form id replaces both. Flushes; the caller commits."""
    if definition.get("type") != "form" or not isinstance(definition.get("id"), int):
        raise InspectionError("Not a GoCanvas form definition")
    form = db.scalar(
        select(InspectionForm).where(
            InspectionForm.operator_id == operator_id,
            InspectionForm.gocanvas_form_id == definition["id"],
        )
    )
    if form is None:
        form = InspectionForm(operator_id=operator_id, gocanvas_form_id=definition["id"])
        db.add(form)
    form.kind = kind
    form.name = (definition.get("name") or f"Form {definition['id']}")[:300]
    form.version = definition.get("version")
    form.gocanvas_root_version_id = definition.get("root_version_id")
    form.definition = definition
    form.imported_at = datetime.now(UTC)
    form.zones.clear()
    form.fields.clear()
    db.flush()

    zone_sections = {
        section["id"]
        for section, entry in _entries(definition)
        if _normalize(entry.get("label") or "").startswith(INSPECTED_QUESTION)
    }
    zone_keys: dict[int, str] = {}
    for section in definition.get("sections") or []:
        if section["id"] in zone_sections:
            key = _slug(section.get("description") or str(section["id"]))
            zone_keys[section["id"]] = key
            form.zones.append(
                InspectionFormZone(
                    gocanvas_section_id=section["id"],
                    zone_key=key,
                    name=(section.get("description") or key)[:300],
                    position=len(form.zones),
                )
            )

    for position, (section, entry) in enumerate(_entries(definition)):
        label = entry.get("label") or ""
        section_name = _normalize(section.get("description") or "")
        zone_key = zone_keys.get(section["id"])
        field_key = _match(label, SUMMARY_FIELDS)
        if field_key is None:
            if zone_key is not None:
                field_key = _match(label, ZONE_FIELDS)
            elif section_name == "material use":
                field_key = MATERIAL_PREFIX + _slug(label.split("(")[0])
            else:
                field_key = _match(label, HEADER_FIELDS)
        options = [
            value["text"].strip()
            for value in sorted(entry.get("entry_values") or [], key=lambda v: v["position"])
        ]
        form.fields.append(
            InspectionFormField(
                entry_id=entry["id"],
                gocanvas_section_id=section["id"],
                zone_key=zone_key if field_key not in dict(SUMMARY_FIELDS).values() else None,
                field_key=field_key,
                entry_type_id=entry.get("entry_type_id") or 0,
                label=label[:500],
                export_label=entry.get("export_label"),
                required=bool(entry.get("required")),
                options=options,
                multi_select=bool(options)
                and entry.get("minimum") is None
                and entry.get("maximum") is None,
                position=position,
            )
        )
    db.flush()
    return form


# --- Value parsing ----------------------------------------------------------------------------


@dataclass
class _Warnings:
    items: list[dict] = field(default_factory=list)

    def add(self, response: dict, field_key: str | None, issue: str) -> None:
        value = response.get("value")
        self.items.append(
            {
                "entry_id": response.get("entry_id"),
                "field_key": field_key,
                "value": value if isinstance(value, str) else json.dumps(value),
                "issue": issue,
            }
        )


def _text(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def split_options(value: str | None, options: list[str]) -> tuple[list[str], list[str]]:
    """Split a multi-select answer into (values, values not among `options`).

    GoCanvas joins selections with "\\r\\n"; older submissions used "\\n" or ",". Commas are
    split only outside known options, since one option ("... (Wall Junction, IT Cabinet, &
    Internals)") contains them."""
    text = _text(value)
    if text is None:
        return [], []
    known = {option.casefold(): option for option in options}
    found: list[tuple[int, str]] = []
    offset = 0
    for line in re.split(r"\r?\n", text):
        line_start = offset
        offset += len(line) + 1
        line = line.strip()
        if not line:
            continue
        if line.casefold() in known or "," not in line:
            found.append((line_start, known.get(line.casefold(), line)))
            continue
        rest = line
        for option in sorted(options, key=len, reverse=True):
            index = rest.casefold().find(option.casefold())
            if option and index >= 0:
                found.append((line_start + index, option))
                rest = rest[:index] + "," * len(option) + rest[index + len(option) :]
        position = 0
        for piece in rest.split(","):
            if piece.strip():
                found.append((line_start + position, piece.strip()))
            position += len(piece) + 1
    values = [v for _, v in sorted(found, key=lambda item: item[0])]
    values = list(dict.fromkeys(values))
    unknown = [v for v in values if options and v.casefold() not in known]
    return values, unknown


def _yes_no(value) -> bool | None | str:
    """True/False for Yes/No, None for blank; the stripped text for anything else."""
    text = _text(value)
    if text is None:
        return None
    lowered = text.casefold()
    if lowered == "yes":
        return True
    if lowered == "no":
        return False
    return text


def _score(value, low: int, high: int) -> int | None | str:
    text = _text(value)
    if text is None:
        return None
    match = re.fullmatch(r"(?:ramp\s*)?(\d+)(?:\.0+)?", text, flags=re.IGNORECASE)
    if match and low <= int(match.group(1)) <= high:
        return int(match.group(1))
    return text


def _inspected_at(date: str | None, time: str | None) -> datetime | None | str:
    """The form's Date ("10/28/2026") and Time ("05:07 AM", sometimes "9:12 PM"); the text
    when they can't be read."""
    date, time = _text(date), _text(time)
    if date is None:
        return None
    raw, fmt = (f"{date} {time}", "%m/%d/%Y %I:%M %p") if time else (date, "%m/%d/%Y")
    try:
        return datetime.strptime(raw, fmt)
    except ValueError:
        return raw


def _store_number(label: str | None) -> str | None:
    match = re.search(r"#\s*(\d+)", label or "")
    return match.group(1) if match else None


def _parse_datetime(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- Submissions ------------------------------------------------------------------------------


@dataclass
class StoreResult:
    submission: InspectionSubmission
    outcome: str  # "created", "updated", "unchanged", or "stale" (an older revision; ignored)


def store_submission(
    db: Session,
    operator_id: uuid.UUID,
    payload: dict,
    *,
    gocanvas_request_id: uuid.UUID | None = None,
    reparse: bool = False,
) -> StoreResult:
    """Parse a GoCanvas submission (GET /submissions/{id}) and store it, replacing an earlier
    copy of the same submission. An unchanged payload is skipped unless `reparse` (after the
    parsing rules change). Flushes; the caller commits."""
    if payload.get("type") != "submission" or not isinstance(payload.get("id"), int):
        raise InspectionError("Not a GoCanvas submission")
    form = db.scalar(
        select(InspectionForm).where(
            InspectionForm.operator_id == operator_id,
            InspectionForm.gocanvas_form_id == payload.get("form_id"),
        )
    )
    if form is None:
        raise InspectionError(f"GoCanvas form {payload.get('form_id')} hasn't been imported")

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sha256 = hashlib.sha256(canonical.encode()).hexdigest()
    revised_at = _parse_datetime(payload.get("revised_at"))
    submission = db.scalar(
        select(InspectionSubmission).where(
            InspectionSubmission.operator_id == operator_id,
            InspectionSubmission.gocanvas_submission_id == payload["id"],
        )
    )
    payload_changed = submission is None or submission.payload_sha256 != sha256
    if submission is not None:
        if not payload_changed and not reparse:
            return StoreResult(submission, "unchanged")
        if submission.revised_at and (revised_at is None or revised_at < submission.revised_at):
            return StoreResult(submission, "stale")
        outcome = "updated"
        submission.responses.clear()
        submission.risk_zones.clear()
        submission.risk_materials.clear()
        submission.risk_summary = None
        db.flush()
    else:
        submission = InspectionSubmission(
            operator_id=operator_id, gocanvas_submission_id=payload["id"]
        )
        db.add(submission)
        outcome = "created"

    submission.form = form
    submission.gocanvas_request_id = gocanvas_request_id or submission.gocanvas_request_id
    submission.gocanvas_form_id = payload["form_id"]
    submission.submission_number = payload.get("submission_number")
    submission.client_guid = payload.get("client_guid")
    submission.device_guid = payload.get("device_guid")
    submission.gocanvas_user_id = payload.get("user_id")
    submission.gocanvas_department_id = payload.get("department_id")
    submission.status = payload.get("status")
    submission.is_revision = bool(payload.get("revision"))
    submission.gocanvas_created_at = _parse_datetime(payload.get("created_at"))
    submission.revised_at = revised_at
    submission.raw_payload = payload
    submission.payload_sha256 = sha256
    submission.parsed_at = datetime.now(UTC)

    _parse_into(db, submission, form, payload.get("responses") or [])
    sync_photo_values(submission, refetch=payload_changed)
    db.flush()
    _sync_file_companies(db, submission)
    return StoreResult(submission, outcome)


def _sync_file_companies(db: Session, submission: InspectionSubmission) -> None:
    """Keep the submission's stored photos on the company of its (possibly new) location."""
    file_ids = list(
        db.scalars(
            select(InspectionPhoto.file_id)
            .join(InspectionPhotoValue, InspectionPhotoValue.id == InspectionPhoto.photo_value_id)
            .where(InspectionPhotoValue.submission_id == submission.id)
        )
    )
    files.set_company(db, file_ids, files.company_for_location(db, submission.location_id))


PHOTO_RESPONSE_TYPE = "Multi Photo"
PHOTO_CATEGORIES = {
    "photos_pest": "pest",
    "photos_sanitation": "sanitation",
    "photos_structural": "structural",
    "photos_additional": "additional",
}


def sync_photo_values(submission: InspectionSubmission, *, refetch: bool = False) -> None:
    """Record the submission's photo fields that have images, from its stored responses.

    A Multi Photo response with images holds the text "Binary data is not displayed"; one
    without holds []. Values a revision drops get `removed_at`. With `refetch` (the payload
    changed), stored values are fetched again, since a revision may change their images."""
    now = datetime.now(UTC)
    existing = {value.gocanvas_value_id: value for value in submission.photo_values}
    present: set[int] = set()
    for response in submission.responses:
        if response.response_type != PHOTO_RESPONSE_TYPE or not (response.value or "").strip():
            continue
        value_id = response.gocanvas_response_id
        present.add(value_id)
        value = existing.get(value_id)
        if value is None:
            value = InspectionPhotoValue(gocanvas_value_id=value_id)
            submission.photo_values.append(value)
        elif refetch or value.removed_at is not None:
            value.fetched_at = None
        value.entry_id = response.entry_id
        value.zone_key = response.zone_key
        value.category = PHOTO_CATEGORIES.get(response.field_key or "")
        value.label = response.label
        value.removed_at = None
    for value_id, value in existing.items():
        if value_id not in present and value.removed_at is None:
            value.removed_at = now


def _parse_into(
    db: Session, submission: InspectionSubmission, form: InspectionForm, responses: list[dict]
) -> None:
    fields = {f.entry_id: f for f in form.fields}
    warnings = _Warnings()
    unmapped: list[int] = []
    header: dict[str, object] = {}
    summary: dict[str, object] = {}
    zones: dict[str, dict] = {}
    materials: list[tuple[InspectionFormField, dict]] = []

    for position, response in enumerate(responses):
        entry_id = response.get("entry_id")
        form_field = fields.get(entry_id)
        value = response.get("value")
        submission.responses.append(
            InspectionResponse(
                gocanvas_response_id=response.get("id") or 0,
                entry_id=entry_id,
                position=position,
                response_type=(response.get("type") or "")[:50],
                label=(response.get("label") or "")[:500] or None,
                export_label=response.get("export_label"),
                displayed=bool(response.get("displayed")),
                value=value if isinstance(value, str) else None,
                value_json=None if isinstance(value, str) else value,
                zone_key=form_field.zone_key if form_field else None,
                field_key=form_field.field_key if form_field else None,
            )
        )
        if form_field is None or form_field.field_key is None:
            unmapped.append(entry_id)
            warnings.add(response, None, "entry not in the form's field map")
            continue
        key = form_field.field_key
        if key.startswith(MATERIAL_PREFIX):
            materials.append((form_field, response))
        elif key in dict(SUMMARY_FIELDS).values():
            summary[key] = (form_field, response)
        elif form_field.zone_key is not None:
            zones.setdefault(form_field.zone_key, {})[key] = (form_field, response)
        else:
            header[key] = (form_field, response)

    _parse_header(submission, header, warnings)
    if form.kind is InspectionKind.risk:
        for zone in form.zones:
            submission.risk_zones.append(_parse_zone(zone, zones.get(zone.zone_key, {}), warnings))
        submission.risk_materials.extend(
            _parse_material(form_field, response, warnings) for form_field, response in materials
        )
        submission.risk_summary = _parse_summary(summary, warnings)
    submission.parse_warnings = warnings.items
    submission.unmapped_entry_ids = unmapped
    _link(db, submission)


def _value(fields: dict, key: str):
    pair = fields.get(key)
    return pair[1].get("value") if pair else None


def _parse_header(submission: InspectionSubmission, header: dict, warnings: _Warnings) -> None:
    submission.inspector_name = (_text(_value(header, "inspector_name")) or "")[:200] or None
    inspected_at = _inspected_at(_value(header, "date"), _value(header, "time"))
    if isinstance(inspected_at, str):
        warnings.add(header["date"][1], "date", f"unreadable date/time {inspected_at!r}")
        inspected_at = None
    submission.inspected_at = inspected_at
    submission.store_label = (_text(_value(header, "store")) or "")[:200] or None
    submission.store_number = _store_number(submission.store_label)
    submission.address = (_text(_value(header, "address")) or "")[:300] or None
    submission.city = (_text(_value(header, "city")) or "")[:100] or None
    submission.work_order_ref = (_text(_value(header, "work_order_ref")) or "")[:100] or None


def _boolean(fields: dict, key: str, warnings: _Warnings) -> bool | None:
    if key not in fields:
        return None
    result = _yes_no(fields[key][1].get("value"))
    if isinstance(result, str):
        warnings.add(fields[key][1], key, "expected Yes or No")
        return None
    return result


def _options(fields: dict, key: str, warnings: _Warnings) -> list[str]:
    if key not in fields:
        return []
    form_field, response = fields[key]
    values, unknown = split_options(response.get("value"), form_field.options)
    for value in unknown:
        warnings.add(response, key, f"{value!r} is not one of the form's options")
    return values


def _risk(fields: dict, key: str, warnings: _Warnings) -> int | None:
    if key not in fields:
        return None
    result = _score(fields[key][1].get("value"), 1, 5)
    if isinstance(result, str):
        warnings.add(fields[key][1], key, "expected a risk score from 1 to 5")
        return None
    return result


def _parse_zone(zone: InspectionFormZone, fields: dict, warnings: _Warnings) -> RiskInspectionZone:
    inspected = _text(_value(fields, "inspected"))
    if inspected is not None:
        inspected = {"yes": "yes", "no": "no", "n/a": "n/a"}.get(inspected.casefold())
        if inspected is None:
            warnings.add(fields["inspected"][1], "inspected", "expected Yes, No, or N/A")
    attributes: dict[str, object] = {}
    for key in fields:
        if key.startswith("attr."):
            name = key.removeprefix("attr.")
            if name in BOOLEAN_ATTRIBUTES:
                value = _boolean(fields, key, warnings)
                if value is not None:
                    attributes[name] = value
            elif values := _options(fields, key, warnings):
                attributes[name] = values
    return RiskInspectionZone(
        zone_key=zone.zone_key,
        name=zone.name,
        position=zone.position,
        inspected=inspected,
        all_areas_inspected=_boolean(fields, "all_areas_inspected", warnings),
        areas=_options(fields, "areas", warnings),
        doors_are=_options(fields, "doors_are", warnings),
        door_sweeps_ok=_boolean(fields, "door_sweeps_ok", warnings),
        doors_aligned=_boolean(fields, "doors_aligned", warnings),
        rodent_activity=_boolean(fields, "rodent_activity", warnings),
        pest_activity=_boolean(fields, "pest_activity", warnings),
        pest_types=[
            PEST_TYPE_ALIASES.get(p.casefold(), p) for p in _options(fields, "pest_types", warnings)
        ],
        additional_notes=_text(_value(fields, "additional_notes")),
        pest_notes=_text(_value(fields, "pest_notes")),
        sanitation_notes=_text(_value(fields, "sanitation_notes")),
        structural_notes=_text(_value(fields, "structural_notes")),
        sanitation_risk=_risk(fields, "sanitation_risk", warnings),
        structural_risk=_risk(fields, "structural_risk", warnings),
        overall_risk=_risk(fields, "overall_risk", warnings),
        attributes=attributes,
    )


def _parse_material(
    form_field: InspectionFormField, response: dict, warnings: _Warnings
) -> RiskInspectionMaterial:
    raw = _text(response.get("value"))
    used: bool | None = None
    quantity: Decimal | None = None
    answer = _yes_no(raw)
    if isinstance(answer, bool):
        used = answer
    elif isinstance(answer, str):
        try:
            quantity = Decimal(answer)
            used = quantity > 0
        except InvalidOperation:
            warnings.add(response, form_field.field_key, "expected Yes, No, or a quantity")
    return RiskInspectionMaterial(
        material_key=form_field.field_key.removeprefix(MATERIAL_PREFIX)[:100],
        name=form_field.label.strip()[:200],
        used=used,
        quantity=quantity,
        raw_value=(raw or "")[:200] or None,
    )


def _parse_summary(summary: dict, warnings: _Warnings) -> RiskInspectionSummary:
    ramp = None
    if "ramp_recommendation" in summary:
        ramp = _score(summary["ramp_recommendation"][1].get("value"), 1, 3)
        if isinstance(ramp, str):
            warnings.add(summary["ramp_recommendation"][1], "ramp_recommendation", "unknown RAMP")
            ramp = None
    return RiskInspectionSummary(
        ramp_recommendation=ramp,
        manager_summary=_text(_value(summary, "manager_summary")),
        material_notes=_text(_value(summary, "material_notes")),
    )


def _link(db: Session, submission: InspectionSubmission) -> None:
    """Link the service order by the work order number (a PestPac order number), and the
    location through it; else the location whose name ends with the store number."""
    submission.service_order_id = None
    submission.location_id = None
    ref = submission.work_order_ref or ""
    if ref.isdigit():
        order = db.scalar(
            select(ServiceOrder).where(
                ServiceOrder.operator_id == submission.operator_id,
                ServiceOrder.order_number == ref,
            )
        )
        if order is not None:
            submission.service_order_id = order.id
            submission.location_id = order.location_id
    if submission.location_id is None and submission.store_number:
        matches = db.scalars(
            select(Location.id)
            .where(
                Location.operator_id == submission.operator_id,
                func.upper(Location.pestpac_company).like(f"%#{submission.store_number}"),
            )
            .limit(2)
        ).all()
        if len(matches) == 1:
            submission.location_id = matches[0]
