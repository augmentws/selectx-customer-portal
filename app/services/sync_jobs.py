"""Queue and run service-order sync jobs (processed by `python -m app.worker`)."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BillTo, Location, SyncJob, SyncJobKind, SyncJobStatus, Tenant
from app.schemas.pestpac import NoteSyncCounts, ServiceOrderSyncCounts
from app.services import notes, pestpac_connection, service_orders
from app.services import technicians as technicians_service
from app.services.pestpac_connection import ConnectionNotReadyError, PestPacUnavailableError
from app.services.technicians import TechnicianResolver

log = logging.getLogger(__name__)

ACTIVE = (SyncJobStatus.queued, SyncJobStatus.running)


def _enqueue(
    db: Session,
    *,
    kind: SyncJobKind,
    bill_to: BillTo,
    location: Location | None,
    requested_by: uuid.UUID | None,
) -> SyncJob:
    """Queue a job unless the same one is already queued or running. Does not commit."""
    same_target = SyncJob.location_id == location.id if location else SyncJob.location_id.is_(None)
    existing = db.scalar(
        select(SyncJob).where(
            SyncJob.kind == kind,
            SyncJob.bill_to_id == bill_to.id,
            same_target,
            SyncJob.status.in_(ACTIVE),
        )
    )
    if existing is not None:
        return existing
    job = SyncJob(
        operator_id=bill_to.operator_id,
        kind=kind,
        bill_to_id=bill_to.id,
        location_id=location.id if location else None,
        requested_by=requested_by,
        status=SyncJobStatus.queued,
        progress={},
        attempts=0,
    )
    db.add(job)
    db.flush()
    return job


def enqueue_bill_to(db: Session, bill_to: BillTo, requested_by: uuid.UUID | None) -> SyncJob:
    return _enqueue(
        db,
        kind=SyncJobKind.bill_to_service_orders,
        bill_to=bill_to,
        location=None,
        requested_by=requested_by,
    )


def enqueue_location(db: Session, location: Location, requested_by: uuid.UUID | None) -> SyncJob:
    bill_to = db.get(BillTo, location.bill_to_id)
    return _enqueue(
        db,
        kind=SyncJobKind.location_service_orders,
        bill_to=bill_to,
        location=location,
        requested_by=requested_by,
    )


def claim_next(db: Session) -> SyncJob | None:
    """Claim the oldest queued job, or a running one whose worker stopped heart-beating."""
    settings = get_settings()
    stale_before = datetime.now(UTC) - timedelta(minutes=settings.sync_job_stale_minutes)
    job = db.scalar(
        select(SyncJob)
        .where(
            or_(
                SyncJob.status == SyncJobStatus.queued,
                (SyncJob.status == SyncJobStatus.running) & (SyncJob.heartbeat_at < stale_before),
            )
        )
        .order_by(SyncJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    now = datetime.now(UTC)
    if job.attempts >= settings.sync_job_max_attempts:
        job.status = SyncJobStatus.failed
        job.error = f"Gave up after {job.attempts} attempts (worker stopped mid-job)"
        job.finished_at = now
        db.commit()
        return None
    job.status = SyncJobStatus.running
    job.attempts += 1
    job.started_at = job.started_at or now
    job.heartbeat_at = now
    db.commit()
    return job


def _finish(db: Session, job: SyncJob, status: SyncJobStatus, error: str | None = None) -> None:
    job.status = status
    job.error = error[:1000] if error else None
    job.finished_at = datetime.now(UTC)
    db.commit()


def run_job(db: Session, job: SyncJob) -> SyncJob:
    """Sync each location's open orders, committing per location so one failure doesn't undo
    the rest. Ends `succeeded`, `partial` (some locations failed), or `failed`."""
    operator = db.get(Tenant, job.operator_id)
    try:
        client = pestpac_connection.get_pestpac_client(db, operator)
    except ConnectionNotReadyError as exc:
        _finish(db, job, SyncJobStatus.failed, str(exc))
        return job

    if job.kind == SyncJobKind.location_service_orders:
        locations = [db.get(Location, job.location_id)]
    else:
        locations = list(
            db.scalars(
                select(Location)
                .where(Location.bill_to_id == job.bill_to_id, Location.removed_at.is_(None))
                .order_by(Location.pestpac_company, Location.id)
            )
        )

    totals = ServiceOrderSyncCounts()
    note_totals = NoteSyncCounts()
    technicians = TechnicianResolver(db, client, job.operator_id)
    failed: list[dict] = []
    notes_failed: list[dict] = []
    progress: dict = {"locations_total": len(locations), "locations_done": 0}

    # Seed technicians first so orders and note authors link without per-tech lookups. Not fatal:
    # the per-TechID lookup still covers anyone missing.
    try:
        progress["technicians"] = technicians_service.seed_technicians(db, client, job.operator_id)
        db.commit()
    except PestPacUnavailableError as exc:
        db.rollback()
        log.warning("Technician seeding failed: %s", exc)
        progress["technicians"] = {"error": str(exc)[:300]}
    job = db.get(SyncJob, job.id)
    job.progress = dict(progress)
    db.commit()

    for done, location in enumerate(locations, start=1):
        try:
            counts = service_orders.sync_location(db, client, location, technicians)
            db.commit()
            _add(totals, counts)
        except PestPacUnavailableError as exc:
            db.rollback()
            technicians.forget_uncommitted()
            log.warning("Orders for location %s failed: %s", location.pestpac_location_id, exc)
            failed.append(
                {"pestpac_location_id": location.pestpac_location_id, "error": str(exc)[:300]}
            )
        else:
            # Notes after the orders are committed, so they can link to them; a notes failure
            # never undoes the orders.
            try:
                _add(note_totals, notes.sync_location_notes(db, client, location))
                db.commit()
            except PestPacUnavailableError as exc:
                db.rollback()
                log.warning("Notes for location %s failed: %s", location.pestpac_location_id, exc)
                notes_failed.append(
                    {"pestpac_location_id": location.pestpac_location_id, "error": str(exc)[:300]}
                )
        job = db.get(SyncJob, job.id)
        job.progress = {
            **progress,
            "locations_done": done,
            "failed_locations": failed,
            "notes_failed_locations": notes_failed,
            "orders": totals.model_dump(),
            "notes": note_totals.model_dump(),
        }
        job.heartbeat_at = datetime.now(UTC)
        db.commit()

    if failed and len(failed) == len(locations):
        _finish(db, job, SyncJobStatus.failed, "Every location failed; see progress")
    elif failed or notes_failed:
        problems = [
            f"{len(failed)} location(s) failed" if failed else "",
            f"notes failed for {len(notes_failed)} location(s)" if notes_failed else "",
        ]
        _finish(db, job, SyncJobStatus.partial, "; ".join(p for p in problems if p))
    else:
        _finish(db, job, SyncJobStatus.succeeded)
    return job


def _add(total: BaseModel, counts: BaseModel) -> None:
    for field in type(total).model_fields:
        setattr(total, field, getattr(total, field) + getattr(counts, field))


def jobs_for_bill_to(db: Session, bill_to_id: uuid.UUID, limit: int = 10) -> list[SyncJob]:
    return list(
        db.scalars(
            select(SyncJob)
            .where(SyncJob.bill_to_id == bill_to_id)
            .order_by(SyncJob.created_at.desc())
            .limit(limit)
        )
    )
