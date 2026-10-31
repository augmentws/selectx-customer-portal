"""PestPac areas for a location: GET /Locations/{id}/areas returns the location's areas as a tree
(not paged; an empty list when none are set up), each node an `Entity` with its `ChildNodes`.

Synced by "Sync location" before the location's conditions, which name their area by AreaID;
`link_conditions` then points the location's conditions at their stored area.
"""

import uuid
from datetime import UTC, datetime

import requests
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.integrations.pestpac import PestPacAuthError, PestPacClient
from app.models import Condition, Location, LocationArea
from app.schemas.pestpac import AreaSyncCounts, PestPacArea
from app.services.pestpac_connection import PestPacUnavailableError

# PestPac's areas nest a few levels; a deeper tree means a malformed response.
MAX_DEPTH = 20


def _flatten(nodes: object, depth: int, out: list[PestPacArea]) -> None:
    if not isinstance(nodes, list) or depth > MAX_DEPTH:
        raise PestPacUnavailableError("PestPac returned an unexpected areas response")
    for node in nodes:
        entity = node.get("Entity") if isinstance(node, dict) else None
        if not isinstance(entity, dict) or not isinstance(entity.get("AreaID"), int):
            raise PestPacUnavailableError("PestPac returned an unexpected areas response")
        out.append(PestPacArea.from_api(entity, depth))
        _flatten(node.get("ChildNodes") or [], depth + 1, out)


def fetch_location_areas(client: PestPacClient, pestpac_location_id: int) -> list[PestPacArea]:
    path = f"/Locations/{pestpac_location_id}/areas"
    try:
        response = client.custom_endpoint(path).get()
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise PestPacUnavailableError(f"PestPac {path} returned {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        body = None
    areas: list[PestPacArea] = []
    _flatten(body, 1, areas)
    return areas


def sync_location_areas(
    db: Session, client: PestPacClient, location: Location, counts: AreaSyncCounts
) -> None:
    """Upsert the location's areas (moving any PestPac reassigned from another location) and
    mark the ones it no longer lists. Does not commit."""
    listed = fetch_location_areas(client, location.pestpac_location_id)
    now = datetime.now(UTC)
    counts.total += len(listed)
    existing = {
        a.pestpac_area_id: a
        for a in db.scalars(
            select(LocationArea).where(
                LocationArea.operator_id == location.operator_id,
                LocationArea.pestpac_area_id.in_([a.pestpac_area_id for a in listed]),
            )
        )
    }
    for item in listed:
        area = existing.get(item.pestpac_area_id)
        if area is None:
            area = LocationArea(operator_id=location.operator_id)
            db.add(area)
            existing[item.pestpac_area_id] = area
            counts.added += 1
        else:
            counts.updated += 1
        for field in PestPacArea.model_fields:
            setattr(area, field, getattr(item, field))
        area.location_id = location.id
        area.pestpac_location_id = location.pestpac_location_id
        area.removed_at = None
        area.pestpac_fetched_at = now
    db.flush()  # parents need their ids
    for item in listed:
        parent = existing.get(item.pestpac_parent_id) if item.pestpac_parent_id else None
        existing[item.pestpac_area_id].parent_id = parent.id if parent else None

    listed_ids = [a.pestpac_area_id for a in listed]
    gone = [LocationArea.location_id == location.id, LocationArea.removed_at.is_(None)]
    if listed_ids:
        gone.append(LocationArea.pestpac_area_id.not_in(listed_ids))
    for area in db.scalars(select(LocationArea).where(*gone)):
        area.removed_at = now
        counts.removed += 1
    db.flush()


def link_conditions(db: Session, location: Location, counts: AreaSyncCounts) -> None:
    """Point the location's conditions at the stored area their AreaID names (or at none, if
    it isn't stored). Run after both the areas and the conditions are synced. Does not commit."""
    area_id = (
        select(LocationArea.id)
        .where(
            LocationArea.operator_id == Condition.operator_id,
            LocationArea.pestpac_area_id == Condition.pestpac_area_id,
        )
        .scalar_subquery()
    )
    result = db.execute(
        update(Condition)
        .where(
            Condition.location_id == location.id,
            Condition.location_area_id.is_distinct_from(area_id),
        )
        .values(location_area_id=area_id)
        .execution_options(synchronize_session=False)
    )
    counts.conditions_linked += result.rowcount


def list_for_location(db: Session, location_id: uuid.UUID) -> list[tuple[LocationArea, int]]:
    """The location's current areas in tree order (each parent, then its children by name),
    each with its count of open conditions."""
    areas = db.scalars(
        select(LocationArea)
        .where(LocationArea.location_id == location_id, LocationArea.removed_at.is_(None))
        .order_by(LocationArea.name, LocationArea.pestpac_area_id)
    ).all()
    open_counts = dict(
        db.execute(
            select(Condition.location_area_id, func.count())
            .where(
                Condition.location_id == location_id,
                Condition.removed_at.is_(None),
                Condition.status == "Open",
                Condition.location_area_id.is_not(None),
            )
            .group_by(Condition.location_area_id)
        ).all()
    )
    ids = {a.id for a in areas}
    children: dict[uuid.UUID | None, list[LocationArea]] = {}
    for area in areas:
        # An area whose parent isn't current is shown at the top.
        children.setdefault(area.parent_id if area.parent_id in ids else None, []).append(area)
    ordered: list[tuple[LocationArea, int]] = []

    def walk(parent_id: uuid.UUID | None) -> None:
        for area in children.get(parent_id, []):
            ordered.append((area, open_counts.get(area.id, 0)))
            walk(area.id)

    walk(None)
    return ordered
