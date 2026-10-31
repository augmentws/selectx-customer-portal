"""The operator's area mapping: which zone (app.models.Zone) each PestPac area type counts as, and
the operator's display names for the zones.

PestPac's area types come from GET /lookups/AreaTypes (one unpaged array of {AreaTypeID, Code,
Description}), synced on request. A location area's zone is its type's zone, found by Code
(`location_areas.area_type`). Areas with no type, or a type left unmapped, have no zone; findings
read from notes get their zone from the LLM instead (app/services/inspection_findings.py).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.pestpac import PestPacAuthError, PestPacClient
from app.models import DEFAULT_ZONE_NAMES, AreaType, LocationArea, Zone, ZoneLabel
from app.services.pestpac_connection import PestPacUnavailableError

# The zone a newly synced type starts with, by Code; unlisted codes (generic ones like INTERIOR
# or FLOOR, and other trades' like APARTMENT or MTA BUS) start unmapped. Editable afterwards.
DEFAULT_ZONES: dict[str, Zone] = {
    "EXTERIOR": Zone.exterior_perimeter,
    "EXT PERIM": Zone.exterior_perimeter,
    "GARAGE": Zone.exterior_perimeter,
    "MGEXTERIOR": Zone.exterior_perimeter,
    "TRASH": Zone.dumpster_waste,
    "COMPACT RM": Zone.dumpster_waste,
    "COMPACTOR": Zone.dumpster_waste,
    "TRSH CHUTE": Zone.dumpster_waste,
    "CHUTE RM": Zone.dumpster_waste,
    "RE/TRASHRM": Zone.dumpster_waste,
    "MGDUMPSTER": Zone.dumpster_waste,
    "MGBACKDOCK": Zone.receiving_delivery,
    "STORAGE": Zone.dry_food_storage,
    "FOOD STOR": Zone.dry_food_storage,
    "STORAGE RM": Zone.dry_food_storage,
    "MGSTORAGE": Zone.dry_food_storage,
    "MGBANQSTOR": Zone.dry_food_storage,
    "KITCHEN": Zone.food_preparation,
    "FOOD PROC": Zone.food_preparation,
    "FOODPREP": Zone.food_preparation,
    "KITCHENSPT": Zone.food_preparation,
    "MGPREPAREA": Zone.food_preparation,
    "MGBANQKITC": Zone.food_preparation,
    "MGBANQPREP": Zone.food_preparation,
    "LINEFOODPR": Zone.service_line,
    "MGCOOKLINE": Zone.service_line,
    "MGCOORDINA": Zone.service_line,
    "MGDISHWASH": Zone.dishwashing_drains,
    "MGBEVBREAD": Zone.bar_beverage,
    "MGBARLOUN": Zone.bar_beverage,
    "FRONTHOUSE": Zone.dining_guest,
    "MGDINING": Zone.dining_guest,
    "MGBANQDINI": Zone.dining_guest,
    "MGCARRY": Zone.dining_guest,
    "MGENTRY": Zone.dining_guest,
    "BATHROOM": Zone.restrooms,
    "RESTROOMS": Zone.restrooms,
    "MGBATHROOM": Zone.restrooms,
    "OFFICE": Zone.offices_employee,
    "OFFICEADM": Zone.offices_employee,
    "BOILER RM": Zone.mechanical_utility,
    "HALLWAYS": Zone.mechanical_utility,
    "LAUNDRY RM": Zone.mechanical_utility,
    "METER RM": Zone.mechanical_utility,
    "MGMECHANIC": Zone.mechanical_utility,
    "MGUTILITY": Zone.mechanical_utility,
    "BASEMENT": Zone.basement,
    "CEILING": Zone.ceiling_voids,
    "PANELING": Zone.ceiling_voids,
    "DUMBWTR": Zone.ceiling_voids,
    "MGCEILING": Zone.ceiling_voids,
    "SHARED": Zone.shared_structures,
    "MALL LOC": Zone.shared_structures,
}


@dataclass
class AreaTypeSync:
    total: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0


def _text(value: object, max_len: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:max_len] or None


def fetch_area_types(client: PestPacClient) -> list[dict]:
    try:
        response = client.custom_endpoint("/lookups/AreaTypes").get()
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise PestPacUnavailableError(f"PestPac /lookups/AreaTypes returned {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, list) or not all(
        isinstance(t, dict) and isinstance(t.get("AreaTypeID"), int) and _text(t.get("Code"), 50)
        for t in body
    ):
        raise PestPacUnavailableError("PestPac returned an unexpected area types response")
    return body


def sync_area_types(db: Session, operator_id: uuid.UUID, client: PestPacClient) -> AreaTypeSync:
    """Upsert PestPac's area types. A new type starts with its default zone; a known type keeps
    the zone it was given. Doesn't commit."""
    listed = fetch_area_types(client)
    now = datetime.now(UTC)
    counts = AreaTypeSync(total=len(listed))
    existing = {
        t.pestpac_area_type_id: t
        for t in db.scalars(select(AreaType).where(AreaType.operator_id == operator_id))
    }
    for item in listed:
        code = _text(item["Code"], 50)
        area_type = existing.get(item["AreaTypeID"])
        if area_type is None:
            default = DEFAULT_ZONES.get(code)
            area_type = AreaType(
                operator_id=operator_id,
                pestpac_area_type_id=item["AreaTypeID"],
                zone=default.value if default else None,
            )
            db.add(area_type)
            counts.added += 1
        else:
            counts.updated += 1
        area_type.code = code
        area_type.description = _text(item.get("Description"), 500)
        area_type.removed_at = None
        area_type.pestpac_fetched_at = now
    listed_ids = {t["AreaTypeID"] for t in listed}
    for area_type in existing.values():
        if area_type.pestpac_area_type_id not in listed_ids and area_type.removed_at is None:
            area_type.removed_at = now
            counts.removed += 1
    db.flush()
    return counts


def list_area_types(db: Session, operator_id: uuid.UUID) -> list[tuple[AreaType, int]]:
    """The operator's current area types by code, each with how many current location areas
    carry it."""
    in_use = dict(
        db.execute(
            select(LocationArea.area_type, func.count())
            .where(LocationArea.operator_id == operator_id, LocationArea.removed_at.is_(None))
            .group_by(LocationArea.area_type)
        ).all()
    )
    types = db.scalars(
        select(AreaType)
        .where(AreaType.operator_id == operator_id, AreaType.removed_at.is_(None))
        .order_by(AreaType.code)
    ).all()
    return [(t, in_use.get(t.code, 0)) for t in types]


def areas_of_type(db: Session, area_type: AreaType) -> int:
    """How many current location areas carry the type."""
    return db.scalar(
        select(func.count()).where(
            LocationArea.operator_id == area_type.operator_id,
            LocationArea.area_type == area_type.code,
            LocationArea.removed_at.is_(None),
        )
    )


def zone_names(db: Session, operator_id: uuid.UUID) -> dict[Zone, str]:
    """Every zone's display name for the operator: its own label, else the default."""
    labels = {
        Zone(label.zone): label.display_name
        for label in db.scalars(select(ZoneLabel).where(ZoneLabel.operator_id == operator_id))
    }
    return {zone: labels.get(zone, DEFAULT_ZONE_NAMES[zone]) for zone in Zone}


def set_zone_name(db: Session, operator_id: uuid.UUID, zone: Zone, display_name: str | None):
    """Set the operator's display name for a zone; None (or the default name) restores the
    default. Doesn't commit."""
    label = db.scalar(
        select(ZoneLabel).where(ZoneLabel.operator_id == operator_id, ZoneLabel.zone == zone.value)
    )
    name = (display_name or "").strip()
    if not name or name == DEFAULT_ZONE_NAMES[zone]:
        if label is not None:
            db.delete(label)
    elif label is None:
        db.add(ZoneLabel(operator_id=operator_id, zone=zone.value, display_name=name))
    else:
        label.display_name = name
    db.flush()
