"""Resolve a service order's TechID1 to our technicians table, fetching from PestPac only when
we don't have the technician yet."""

import logging
import uuid
from datetime import UTC, datetime

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.pestpac import PestPacAuthError, PestPacClient
from app.models import Technician
from app.schemas.pestpac import PestPacTechnicianDetails, ServiceOrderSyncCounts
from app.services.pestpac_connection import PestPacUnavailableError

log = logging.getLogger(__name__)


def fetch_technician(client: PestPacClient, tech_id: int) -> PestPacTechnicianDetails | None:
    """The technician, or None if PestPac can't provide them (not found or unavailable)."""
    try:
        response = client.lookups("Employees/technicians").get(tech_id)
    except (PestPacAuthError, requests.RequestException) as exc:
        log.warning("Technician %s lookup failed: %s", tech_id, type(exc).__name__)
        return None
    if response.status_code != 200:
        log.warning("Technician %s lookup returned %s", tech_id, response.status_code)
        return None
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("TechID") != tech_id:
        log.warning("Technician %s lookup returned an unexpected response", tech_id)
        return None
    return PestPacTechnicianDetails.from_api(body)


def fetch_all_technicians(client: PestPacClient) -> list[PestPacTechnicianDetails]:
    """Every technician (GET /lookups/Employees/technicians; not paged)."""
    try:
        response = client.lookups("Employees/technicians").get()
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise PestPacUnavailableError(
            f"PestPac /lookups/Employees/technicians returned {response.status_code}"
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, list) or not all(isinstance(t, dict) and "TechID" in t for t in body):
        raise PestPacUnavailableError("PestPac returned an unexpected technicians response")
    return [PestPacTechnicianDetails.from_api(t) for t in body]


def seed_technicians(db: Session, client: PestPacClient, operator_id: uuid.UUID) -> dict:
    """Add and update the operator's technicians from PestPac. Does not commit."""
    fetched = fetch_all_technicians(client)
    existing = {
        t.pestpac_tech_id: t
        for t in db.scalars(select(Technician).where(Technician.operator_id == operator_id))
    }
    now = datetime.now(UTC)
    added = updated = 0
    for details in fetched:
        technician = existing.get(details.pestpac_tech_id)
        if technician is None:
            technician = Technician(operator_id=operator_id)
            db.add(technician)
            added += 1
        else:
            updated += 1
        for field, value in details.model_dump().items():
            setattr(technician, field, value)
        technician.pestpac_fetched_at = now
    db.flush()
    return {"total": len(fetched), "added": added, "updated": updated}


def technician_id_for_username(
    db: Session, operator_id: uuid.UUID, username: str | None
) -> uuid.UUID | None:
    """Our technician for a PestPac username (e.g. a note's CreatedByUser), if they're a tech."""
    if not username:
        return None
    return db.scalar(
        select(Technician.id)
        .where(
            Technician.operator_id == operator_id,
            func.upper(Technician.username) == username.strip().upper(),
        )
        .limit(1)
    )


class TechnicianResolver:
    """Per-job: looks each TechID up at most once. A failed lookup leaves the order unlinked
    (its raw tech_id/tech_name remain) and is retried by the next sync, never failing this one."""

    def __init__(self, db: Session, client: PestPacClient, operator_id: uuid.UUID) -> None:
        self._db = db
        self._client = client
        self._operator_id = operator_id
        self._cache: dict[int, uuid.UUID | None] = {}

    def forget_uncommitted(self) -> None:
        """Call after a rollback: technicians inserted in that transaction no longer exist."""
        self._cache.clear()

    def resolve(self, tech_id: int | None, counts: ServiceOrderSyncCounts) -> uuid.UUID | None:
        if tech_id is None:
            return None
        if tech_id in self._cache:
            return self._cache[tech_id]

        existing = self._db.scalar(
            select(Technician.id).where(
                Technician.operator_id == self._operator_id,
                Technician.pestpac_tech_id == tech_id,
            )
        )
        if existing is not None:
            self._cache[tech_id] = existing
            return existing

        details = fetch_technician(self._client, tech_id)
        if details is None:
            counts.technicians_unresolved += 1
            self._cache[tech_id] = None
            return None
        technician = Technician(
            operator_id=self._operator_id,
            pestpac_fetched_at=datetime.now(UTC),
            **details.model_dump(),
        )
        self._db.add(technician)
        self._db.flush()
        counts.technicians_resolved += 1
        self._cache[tech_id] = technician.id
        return technician.id
