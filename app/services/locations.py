"""Sync a bill-to's service locations from PestPac.

Fetching and writing are separate so callers can fetch everything first and then write in one
transaction: a PestPac failure on page 3 must not leave a half-synced bill-to.
"""

import uuid
from datetime import UTC, datetime

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.pestpac import PestPacAuthError, PestPacClient
from app.models import BillTo, Location
from app.schemas.pestpac import LocationSyncSummary, PestPacLocationDetails
from app.services.pestpac_connection import PestPacUnavailableError


def fetch_locations(client: PestPacClient, pestpac_bill_to_id: int) -> list[PestPacLocationDetails]:
    """All locations PestPac lists under a bill-to, across pages.

    The endpoint returns a bare JSON array with no total, so a short page marks the end.
    """
    settings = get_settings()
    take = settings.pestpac_page_size
    by_id: dict[int, PestPacLocationDetails] = {}
    for page_number in range(settings.pestpac_max_pages):
        page = _fetch_page(client, pestpac_bill_to_id, skip=page_number * take, take=take)
        if page and page[0].pestpac_location_id in by_id:
            # A server that ignores `skip` would otherwise loop until max_pages.
            raise PestPacUnavailableError(
                "PestPac returned the same page of locations twice; paging is not advancing"
            )
        for location in page:
            if location.pestpac_bill_to_id != pestpac_bill_to_id:
                raise PestPacUnavailableError(
                    f"PestPac listed location {location.pestpac_location_id} under BillToID "
                    f"{location.pestpac_bill_to_id}, not {pestpac_bill_to_id}"
                )
            by_id[location.pestpac_location_id] = location
        if len(page) < take:
            return list(by_id.values())
    raise PestPacUnavailableError(
        f"Bill-to {pestpac_bill_to_id} has more than {settings.pestpac_max_pages * take} "
        "locations; raise PESTPAC_MAX_PAGES to sync it"
    )


def _fetch_page(
    client: PestPacClient, pestpac_bill_to_id: int, *, skip: int, take: int
) -> list[PestPacLocationDetails]:
    try:
        response = client.bill_to_locations_page(pestpac_bill_to_id, skip=skip, take=take)
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise PestPacUnavailableError(
            f"PestPac /BillTos/{pestpac_bill_to_id}/locations returned {response.status_code}"
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, list) or not all(
        isinstance(item, dict) and "LocationID" in item and "BillToID" in item for item in body
    ):
        raise PestPacUnavailableError("PestPac returned an unexpected locations response")
    return [PestPacLocationDetails.from_api(item) for item in body]


def apply_locations(
    db: Session, bill_to: BillTo, fetched: list[PestPacLocationDetails]
) -> LocationSyncSummary:
    """Upsert by LocationID within the operator. Does not commit.

    - New locations are added; known ones are updated, and moved here if they had been under
      another bill-to.
    - Locations previously under this bill-to that PestPac no longer lists get `removed_at`.
    """
    now = datetime.now(UTC)
    ids = [f.pestpac_location_id for f in fetched]
    existing = {
        loc.pestpac_location_id: loc
        for loc in db.scalars(
            select(Location).where(
                Location.operator_id == bill_to.operator_id,
                Location.pestpac_location_id.in_(ids),
            )
        )
    }
    added = updated = 0
    for details in fetched:
        location = existing.get(details.pestpac_location_id)
        if location is None:
            location = Location(
                operator_id=bill_to.operator_id,
                pestpac_location_id=details.pestpac_location_id,
            )
            db.add(location)
            added += 1
        else:
            updated += 1
        location.bill_to_id = bill_to.id
        for field in PestPacLocationDetails.model_fields:
            if field not in ("pestpac_location_id", "pestpac_bill_to_id"):
                setattr(location, field, getattr(details, field))
        location.removed_at = None
        location.pestpac_fetched_at = now

    removed = 0
    stale = select(Location).where(
        Location.bill_to_id == bill_to.id,
        Location.removed_at.is_(None),
    )
    if ids:
        stale = stale.where(Location.pestpac_location_id.not_in(ids))
    for location in db.scalars(stale):
        location.removed_at = now
        removed += 1
    db.flush()
    return LocationSyncSummary(total=len(fetched), added=added, updated=updated, removed=removed)


def list_locations(
    db: Session, bill_to_id: uuid.UUID | None = None, *, company_id: uuid.UUID | None = None
) -> list[Location]:
    """One bill-to's locations, or (with `company_id`) those of all the company's bill-tos."""
    query = select(Location)
    if bill_to_id is not None:
        query = query.where(Location.bill_to_id == bill_to_id)
    if company_id is not None:
        query = query.where(
            Location.bill_to_id.in_(select(BillTo.id).where(BillTo.company_id == company_id))
        )
    return list(
        db.scalars(
            query
            # Current locations first, then by store name.
            .order_by(Location.removed_at.is_not(None), Location.pestpac_company, Location.id)
        )
    )


def location_counts(db: Session, bill_to_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Locations PestPac currently lists under each bill-to."""
    if not bill_to_ids:
        return {}
    rows = db.execute(
        select(Location.bill_to_id, func.count())
        .where(Location.bill_to_id.in_(bill_to_ids), Location.removed_at.is_(None))
        .group_by(Location.bill_to_id)
    ).all()
    return dict(rows)
