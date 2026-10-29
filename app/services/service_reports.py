"""Service reports: one service order, one template, edited until final.

1. Started from a service order: snapshot the location, order, and open conditions, and list
   the location's notes and photos dated near the order's work date (PestPac doesn't link
   most notes or photos to an order, so the date is the link). Those on the work date, or
   linked to the order, start selected.
2. The selected notes are drafted into the template's LLM fields by the worker, with the
   template's prompt (they're written together: the prompt names the fields).
3. Edited, previewed as HTML, then finalized: the PDF is rendered from the stored data and
   kept in object storage; the data stays in `reports.data`. A final report is locked;
   revising starts a new draft from a copy.
"""

import base64
import dataclasses
import io
import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, ValidationError, create_model
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.integrations.openrouter import OpenRouterError
from app.models import (
    Condition,
    Document,
    Location,
    Note,
    Report,
    ReportStatus,
    ReportTemplate,
    ServiceOrder,
)
from app.schemas.reports import (
    ReportCondition,
    ReportContext,
    ReportData,
    ReportNoteItem,
    ReportPhoto,
    ReportPhotoItem,
    ReportSection,
    ReportServiceOrder,
    ReportTechnicianComment,
    ReportUpdate,
    TemplateField,
)
from app.services import files, llm_tasks, reports
from app.storage import ObjectStorage, StorageError

log = logging.getLogger(__name__)

# Notes and photos this many days either side of the work date are offered; those on the
# work date itself start selected.
CANDIDATE_DAYS = 1
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tif", ".tiff")
# Photos are downscaled before they're embedded (the originals are full-size phone photos).
PHOTO_MAX_PX = 1600
PHOTO_JPEG_QUALITY = 80


class ReportStateError(RuntimeError):
    """The report isn't in a state that allows this (e.g. editing a final report)."""


class ReportInputError(ValueError):
    """The edit doesn't fit the template's fields or the report's candidates."""


# --- Field values ---------------------------------------------------------------------------


_VALUE_TYPES: dict[str, Any] = {
    "text": str,
    "paragraphs": list[str],
    "list": list[str],
    "sections": list[ReportSection],
}


def _value_model(fields: list[TemplateField], *, name: str, only_llm: bool) -> type[BaseModel]:
    chosen = [f for f in fields if f.llm or not only_llm]
    definitions: dict[str, Any] = {
        f.key: (_VALUE_TYPES[f.type], ...) if only_llm else (_VALUE_TYPES[f.type] | None, None)
        for f in chosen
    }
    return create_model(name, __config__=ConfigDict(extra="forbid"), **definitions)


def default_fields(fields: list[TemplateField]) -> dict[str, Any]:
    """Starting values: each field's default, else empty."""
    return {
        f.key: f.default if f.default is not None else ("" if f.type == "text" else [])
        for f in fields
    }


def validate_fields(fields: list[TemplateField], values: dict[str, Any]) -> dict[str, Any]:
    """Values for known keys, checked against their types (ReportInputError otherwise)."""
    model = _value_model(fields, name="ReportFields", only_llm=False)
    try:
        parsed = model.model_validate(values)
    except ValidationError as exc:
        raise ReportInputError(
            "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        ) from exc
    return parsed.model_dump(mode="json", exclude_unset=True)


# --- Starting a report ----------------------------------------------------------------------


def _service_number(db: Session, order: ServiceOrder) -> int | None:
    """The order's place among the location's worked orders by work date."""
    if order.work_date is None or order.location_id is None:
        return None
    earlier = db.scalars(
        select(ServiceOrder.id).where(
            ServiceOrder.location_id == order.location_id,
            ServiceOrder.posted.is_(True),
            ServiceOrder.work_date <= order.work_date,
            ServiceOrder.id != order.id,
        )
    ).all()
    return len(earlier) + 1


def same_day_window(work_date: datetime | None) -> tuple[datetime, datetime] | None:
    """From the start of the day before the work date to the end of the day after
    (CANDIDATE_DAYS); also used by the service order page."""
    if work_date is None:
        return None
    day = datetime.combine(work_date.date(), time())
    return day - timedelta(days=CANDIDATE_DAYS), day + timedelta(days=CANDIDATE_DAYS + 1)


def _is_image(document: Document) -> bool:
    if document.content_type:
        return document.content_type.startswith("image/")
    return (document.file_name or "").lower().endswith(IMAGE_EXTENSIONS)


def _candidates(
    db: Session, location: Location, order: ServiceOrder
) -> tuple[list[ReportNoteItem], list[ReportPhotoItem]]:
    window = same_day_window(order.work_date)
    work_day = order.work_date.date() if order.work_date else None

    note_filter = [Note.service_order_id == order.id]
    if window:
        note_filter.append(Note.note_date.between(*window))
    notes = db.scalars(
        select(Note)
        .where(Note.location_id == location.id, or_(*note_filter))
        .options(selectinload(Note.created_by_technician))
        .order_by(Note.note_date, Note.id)
    ).all()
    note_items = [
        ReportNoteItem(
            note_id=n.id,
            pestpac_note_id=n.pestpac_note_id,
            note_date=n.note_date,
            note_code=n.note_code,
            author=n.created_by_name,
            text=n.note,
            linked_to_order=n.service_order_id == order.id,
            selected=n.service_order_id == order.id
            or (n.note_date is not None and n.note_date.date() == work_day),
        )
        for n in notes
    ]

    photo_items: list[ReportPhotoItem] = []
    if window:
        documents = db.scalars(
            select(Document)
            .where(
                Document.location_id == location.id,
                Document.removed_at.is_(None),
                Document.document_date.between(*window),
            )
            .order_by(Document.document_date, Document.id)
        ).all()
        photo_items = [
            ReportPhotoItem(
                document_id=d.id,
                pestpac_document_id=d.pestpac_document_id,
                name=d.name,
                file_name=d.file_name,
                document_date=d.document_date,
                selected=d.document_date.date() == work_day,
                caption=d.name,
            )
            for d in documents
            if _is_image(d)
        ]
    return note_items, photo_items


def _snapshot(db: Session, location: Location, order: ServiceOrder) -> dict[str, Any]:
    """Everything the template sees except fields and photos, as JSON."""
    base = reports.build_context(db, location)
    conditions = db.scalars(
        select(Condition)
        .where(
            Condition.location_id == location.id,
            Condition.removed_at.is_(None),
            Condition.status == "Open",
        )
        .order_by(Condition.date_opened, Condition.id)
    ).all()
    context = base.model_copy(
        update={
            "service_order": ReportServiceOrder(
                pestpac_order_id=order.pestpac_order_id,
                order_number=order.order_number,
                work_date=order.work_date,
                service_code=order.service_code,
                description=order.description,
                technician_name=order.technician_name,
                service_number=_service_number(db, order),
            ),
            "conditions": [
                ReportCondition.model_validate(c, from_attributes=True) for c in conditions
            ],
        }
    )
    return context.model_dump(mode="json", exclude={"fields", "photos", "revision", "generated_at"})


def report_ids_for_orders(db: Session, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """Each order's report (its latest revision), for orders that have one."""
    if not order_ids:
        return {}
    rows = db.execute(
        select(Report.service_order_id, Report.id)
        .where(Report.service_order_id.in_(order_ids))
        .order_by(Report.service_order_id, Report.revision.desc(), Report.created_at.desc())
        .distinct(Report.service_order_id)
    ).all()
    return dict(rows)


def _lock_order(db: Session, service_order_id: uuid.UUID) -> None:
    """Serialize starting, revising, and finalizing an order's report."""
    db.execute(select(ServiceOrder.id).where(ServiceOrder.id == service_order_id).with_for_update())


class ReportExistsError(Exception):
    def __init__(self, report_id: uuid.UUID):
        super().__init__("This service order already has a report")
        self.report_id = report_id


def create_report(
    db: Session,
    template: ReportTemplate,
    order: ServiceOrder,
    user_id: uuid.UUID,
) -> Report:
    """Start the order's report. An order has one report (with its revisions), whatever the
    template: ReportExistsError if it already has one."""
    _lock_order(db, order.id)  # two simultaneous starts can't both create one
    existing = db.scalar(select(Report.id).where(Report.service_order_id == order.id).limit(1))
    if existing is not None:
        db.rollback()  # release the lock
        raise ReportExistsError(existing)
    location = db.get(Location, order.location_id)
    notes, photos = _candidates(db, location, order)
    data = ReportData(
        context=_snapshot(db, location, order),
        fields=default_fields(reports.template_fields(template)),
        notes=notes,
        photos=photos,
        technician_comment=(
            ReportTechnicianComment(
                text=order.technician_comment, author=order.technician_name, selected=True
            )
            if order.technician_comment
            else None
        ),
    )
    report = Report(
        operator_id=template.operator_id,
        company_id=template.company_id,
        location_id=location.id,
        service_order_id=order.id,
        template_id=template.id,
        template_version=template.version,
        revision=1,
        status=ReportStatus.draft,
        data=data.model_dump(mode="json"),
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(report)
    db.commit()
    return report


# --- Editing --------------------------------------------------------------------------------


def report_data(report: Report) -> ReportData:
    return ReportData.model_validate(report.data)


def _require_draft(report: Report) -> None:
    if report.status == ReportStatus.final:
        raise ReportStateError("The report is final; revise it to make changes")
    if report.status == ReportStatus.superseded:
        raise ReportStateError("A newer version of this report exists; open the latest version")
    if report.status == ReportStatus.drafting:
        raise ReportStateError("The narrative is being drafted; try again when it's done")


def update_report(
    db: Session,
    report: Report,
    template: ReportTemplate,
    changes: ReportUpdate,
    user_id: uuid.UUID,
) -> Report:
    _require_draft(report)
    data = report_data(report)
    if changes.fields is not None:
        fields = reports.template_fields(template)
        unknown = set(changes.fields) - {f.key for f in fields}
        if unknown:
            raise ReportInputError(f"Unknown fields: {', '.join(sorted(unknown))}")
        data.fields = {**data.fields, **validate_fields(fields, changes.fields)}
    if changes.notes is not None:
        by_id = {n.note_id: n for n in data.notes}
        for choice in changes.notes:
            if choice.note_id not in by_id:
                raise ReportInputError(f"Note {choice.note_id} isn't one of this report's notes")
            by_id[choice.note_id].selected = choice.selected
    if changes.technician_comment_selected is not None:
        if data.technician_comment is None:
            raise ReportInputError("This report has no technician comment")
        data.technician_comment.selected = changes.technician_comment_selected
    if changes.photos is not None:
        by_id = {p.document_id: p for p in data.photos}
        listed = [c.document_id for c in changes.photos]
        if sorted(map(str, listed)) != sorted(map(str, by_id)):
            raise ReportInputError("List every one of the report's photos, in the order wanted")
        reordered = []
        for choice in changes.photos:
            photo = by_id[choice.document_id]
            photo.selected = choice.selected
            photo.caption = choice.caption
            reordered.append(photo)
        data.photos = reordered
    report.data = data.model_dump(mode="json")
    report.updated_by = user_id
    db.commit()
    return report


# --- Narrative draft (worker) ---------------------------------------------------------------


def request_draft(db: Session, report: Report, user_id: uuid.UUID) -> Report:
    _require_draft(report)
    data = report_data(report)
    comment = data.technician_comment
    if not any(n.selected for n in data.notes) and not (comment and comment.selected):
        raise ReportInputError("Select at least one note or the technician comment to draft from")
    report.status = ReportStatus.drafting
    report.draft_requested_at = datetime.now(UTC)
    report.draft_error = None
    report.updated_by = user_id
    db.commit()
    return report


def claim_next_draft(db: Session) -> Report | None:
    """Lock the oldest report waiting for a draft. The lock is held until `run_draft` commits,
    so a worker that dies mid-draft releases it and the report is picked up again."""
    return db.scalar(
        select(Report)
        .where(Report.status == ReportStatus.drafting)
        .order_by(Report.draft_requested_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def mark_draft_crashed(db: Session, report_id: uuid.UUID) -> None:
    report = db.get(Report, report_id)
    report.status = ReportStatus.draft
    report.draft_error = "Drafting failed unexpectedly; see the worker log"
    db.commit()


def draft_instructions(template: ReportTemplate, fields: list[TemplateField]) -> str:
    """The template's prompt, plus a description of each field the reply must fill, so the
    two can't drift apart."""
    lines = [
        f"- {f.key} ({f.type}): {f.label}{f'. {f.help}' if f.help else ''}" for f in fields if f.llm
    ]
    return (
        f"{(template.prompt or '').strip()}\n\n"
        "OUTPUT\n"
        "Reply with a JSON object with exactly these keys. 'paragraphs' and 'list' are arrays "
        "of strings; 'sections' is an array of {heading, paragraphs}. Use **double asterisks** "
        "for bold; no other markup.\n" + "\n".join(lines)
    )


def draft_input(data: ReportData) -> dict[str, Any]:
    context = data.context
    return {
        "location": context.get("location"),
        "store_number": context.get("store_number"),
        "service_order": context.get("service_order"),
        "notes": [
            {
                "date": n.note_date.isoformat() if n.note_date else None,
                "code": n.note_code,
                "author": n.author,
                "text": n.text,
            }
            for n in data.notes
            if n.selected
        ],
        "technician_comment": (
            {"author": data.technician_comment.author, "text": data.technician_comment.text}
            if data.technician_comment and data.technician_comment.selected
            else None
        ),
    }


def run_draft(db: Session, report: Report) -> Report:
    """Fill the template's LLM fields from the selected notes. A failure leaves the report a
    draft with `draft_error` set; it never raises for an LLM problem."""
    template = db.get(ReportTemplate, report.template_id)
    fields = reports.template_fields(template)
    llm_fields = [f for f in fields if f.llm]
    data = report_data(report)
    try:
        if not llm_fields:
            raise ReportInputError("The template has no fields for the LLM to draft")
        if not (template.prompt or "").strip():
            raise ReportInputError("The template has no prompt")
        task = llm_tasks.LLMTask(
            name="service_report",
            instructions=draft_instructions(template, fields),
            output=_value_model(fields, name="ServiceReportDraft", only_llm=True),
            model=template.llm_model,
        )
        result = llm_tasks.run_task(task, draft_input(data))
    except (
        ReportInputError,
        llm_tasks.LLMNotConfiguredError,
        llm_tasks.LLMTaskError,
        OpenRouterError,
    ) as exc:
        log.warning("Draft for report %s failed: %s", report.id, exc)
        report.status = ReportStatus.draft
        report.draft_error = str(exc)[:1000]
        db.commit()
        return report
    data.fields = {**data.fields, **result.output.model_dump(mode="json")}
    report.data = data.model_dump(mode="json")
    report.status = ReportStatus.draft
    report.drafted_at = datetime.now(UTC)
    report.draft_error = None
    report.draft_usage = {
        "model": result.model,
        "attempts": result.attempts,
        **dataclasses.asdict(result.usage),
    }
    db.commit()
    return report


# --- Rendering ------------------------------------------------------------------------------


def _photo_src(storage: ObjectStorage, document: Document) -> str:
    """The stored image, downscaled, as a data: URI."""
    if document.storage_key is None:
        raise ReportInputError(f"Photo {document.pestpac_document_id} isn't stored yet")
    stored = storage.get(document.storage_key)
    try:
        with Image.open(io.BytesIO(stored.data)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((PHOTO_MAX_PX, PHOTO_MAX_PX))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=PHOTO_JPEG_QUALITY)
    except (UnidentifiedImageError, OSError) as exc:
        raise ReportInputError(
            f"Photo {document.pestpac_document_id} can't be read as an image"
        ) from exc
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def build_report_context(
    db: Session, report: Report, storage: ObjectStorage | None
) -> ReportContext:
    data = report_data(report)
    photos: list[ReportPhoto] = []
    selected = [p for p in data.photos if p.selected]
    if selected:
        if storage is None:
            raise StorageError("Object storage is not configured (S3_BUCKET)")
        documents = {
            d.id: d
            for d in db.scalars(
                select(Document).where(Document.id.in_([p.document_id for p in selected]))
            )
        }
        photos = [
            ReportPhoto(src=_photo_src(storage, documents[p.document_id]), caption=p.caption)
            for p in selected
            if p.document_id in documents
        ]
    return ReportContext.model_validate(
        {
            **data.context,
            "fields": data.fields,
            "photos": photos,
            "revision": report.revision,
            "generated_at": report.finalized_at or datetime.now(UTC),
        }
    )


def render_report_html(db: Session, report: Report, storage: ObjectStorage | None) -> str:
    template = db.get(ReportTemplate, report.template_id)
    return reports.render_html(template.html, build_report_context(db, report, storage))


def pdf_storage_key(report: Report) -> str:
    return f"operators/{report.operator_id}/reports/{report.id}/r{report.revision}.pdf"


def finalize(db: Session, report: Report, storage: ObjectStorage, user_id: uuid.UUID) -> Report:
    """Render the PDF from the stored data, store it, and lock the report. Earlier final
    versions of the order's report become superseded: only the newest version is final."""
    _require_draft(report)
    _lock_order(db, report.service_order_id)
    template = db.get(ReportTemplate, report.template_id)
    report.finalized_at = datetime.now(UTC)
    html = reports.render_html(template.html, build_report_context(db, report, storage))
    pdf = reports.html_to_pdf(html)
    report.pdf_file = files.store_file(
        db,
        storage,
        operator_id=report.operator_id,
        company_id=report.company_id,
        source="report_pdf",
        key=pdf_storage_key(report),
        data=pdf,
        content_type="application/pdf",
    )
    report.template_version = template.version
    report.status = ReportStatus.final
    report.finalized_by = user_id
    report.updated_by = user_id
    db.execute(
        update(Report)
        .where(
            Report.service_order_id == report.service_order_id,
            Report.id != report.id,
            Report.status == ReportStatus.final,
        )
        .values(status=ReportStatus.superseded)
    )
    db.commit()
    return report


def revise(db: Session, report: Report, user_id: uuid.UUID) -> Report:
    """A new version (draft) copying the order's latest version, which must be final: versions
    form one line, with at most one draft at a time."""
    _lock_order(db, report.service_order_id)
    latest_id = report_ids_for_orders(db, [report.service_order_id])[report.service_order_id]
    if latest_id != report.id:
        db.rollback()  # release the lock
        raise ReportStateError("Only the latest version can be revised; open the latest version")
    if report.status != ReportStatus.final:
        db.rollback()
        raise ReportStateError("Only a final report can be revised; edit the draft instead")
    template = db.get(ReportTemplate, report.template_id)
    revision = Report(
        operator_id=report.operator_id,
        company_id=report.company_id,
        location_id=report.location_id,
        service_order_id=report.service_order_id,
        template_id=report.template_id,
        template_version=template.version,
        revises_id=report.id,
        revision=report.revision + 1,
        status=ReportStatus.draft,
        data=report.data,
        drafted_at=report.drafted_at,
        draft_usage=report.draft_usage,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(revision)
    db.commit()
    return revision


def list_reports(db: Session, *, location_id: uuid.UUID) -> list[Report]:
    return list(
        db.scalars(
            select(Report)
            .where(Report.location_id == location_id)
            .order_by(Report.created_at.desc(), Report.id)
        )
    )
