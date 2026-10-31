"""Queue and run service-order sync jobs (processed by `python -m app.worker`)."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.pestpac import PestPacClient
from app.models import BillTo, Location, SyncJob, SyncJobKind, SyncJobStatus, Tenant
from app.schemas.pestpac import (
    AreaSyncCounts,
    ConditionSyncCounts,
    DocumentSyncCounts,
    InvoiceSyncCounts,
    NoteSyncCounts,
    ServiceOrderSyncCounts,
)
from app.services import (
    conditions,
    documents,
    invoices,
    location_areas,
    notes,
    pestpac_connection,
    service_orders,
)
from app.services import technicians as technicians_service
from app.services.pestpac_connection import ConnectionNotReadyError, PestPacUnavailableError
from app.services.technicians import TechnicianResolver
from app.storage import StorageError, StorageNotConfiguredError, get_storage

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


def enqueue_location(
    db: Session,
    location: Location,
    requested_by: uuid.UUID | None,
    *,
    kind: SyncJobKind = SyncJobKind.location_service_orders,
) -> SyncJob:
    bill_to = db.get(BillTo, location.bill_to_id)
    return _enqueue(db, kind=kind, bill_to=bill_to, location=location, requested_by=requested_by)


def enqueue_bill_to_location_sync(
    db: Session, bill_to: BillTo, requested_by: uuid.UUID | None
) -> SyncJob:
    return _enqueue(
        db,
        kind=SyncJobKind.bill_to_location_sync,
        bill_to=bill_to,
        location=None,
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
    """Sync each location's open orders, then its notes, invoices, and conditions, committing per
    location so one failure doesn't undo the rest. Ends `succeeded`, `partial` (some locations
    or steps failed), or `failed`."""
    operator = db.get(Tenant, job.operator_id)
    try:
        client = pestpac_connection.get_pestpac_client(db, operator)
    except ConnectionNotReadyError as exc:
        _finish(db, job, SyncJobStatus.failed, str(exc))
        return job

    if job.location_id is not None:
        locations = [db.get(Location, job.location_id)]
    else:
        locations = list(
            db.scalars(
                select(Location)
                .where(Location.bill_to_id == job.bill_to_id, Location.removed_at.is_(None))
                .order_by(Location.pestpac_company, Location.id)
            )
        )

    if job.kind in LOCATION_SYNC_KINDS:
        return _run_location_sync(db, job, client, locations)

    totals = ServiceOrderSyncCounts()
    note_totals = NoteSyncCounts()
    invoice_totals = InvoiceSyncCounts()
    invoices_failed: list[dict] = []
    condition_totals = ConditionSyncCounts()
    conditions_failed: list[dict] = []
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
            # Then the location's invoices (its service history), which also stores orders we
            # never saw listed, such as RAMP program nights; a failure never undoes the orders or
            # notes.
            try:
                _add(
                    invoice_totals,
                    invoices.sync_location_invoices(db, client, location, technicians),
                )
                db.commit()
            except PestPacUnavailableError as exc:
                db.rollback()
                technicians.forget_uncommitted()
                log.warning(
                    "Invoices for location %s failed: %s", location.pestpac_location_id, exc
                )
                invoices_failed.append(
                    {"pestpac_location_id": location.pestpac_location_id, "error": str(exc)[:300]}
                )
            # Then conditions: a posted order is when a technician's new conditions appear.
            # Their documents are stored as rows; files wait for "Sync location", and so do new
            # areas (conditions link to the ones already stored). A failure never undoes the
            # orders, notes, or invoices.
            condition_counts = ConditionSyncCounts()
            try:
                conditions.sync_location_conditions(db, client, location, condition_counts)
                location_areas.link_conditions(db, location, AreaSyncCounts())
                db.commit()
                _add(condition_totals, condition_counts)
            except PestPacUnavailableError as exc:
                db.rollback()
                log.warning(
                    "Conditions for location %s failed: %s", location.pestpac_location_id, exc
                )
                conditions_failed.append(
                    {"pestpac_location_id": location.pestpac_location_id, "error": str(exc)[:300]}
                )
        job = db.get(SyncJob, job.id)
        job.progress = {
            **progress,
            "locations_done": done,
            "failed_locations": failed,
            "notes_failed_locations": notes_failed,
            "invoices_failed_locations": invoices_failed,
            "conditions_failed_locations": conditions_failed,
            "orders": totals.model_dump(),
            "notes": note_totals.model_dump(),
            "invoices": invoice_totals.model_dump(),
            "conditions": condition_totals.model_dump(),
        }
        job.heartbeat_at = datetime.now(UTC)
        db.commit()

    if failed and len(failed) == len(locations):
        _finish(db, job, SyncJobStatus.failed, "Every location failed; see progress")
    elif failed or notes_failed or invoices_failed or conditions_failed:
        problems = [
            f"{len(failed)} location(s) failed" if failed else "",
            f"notes failed for {len(notes_failed)} location(s)" if notes_failed else "",
            f"invoices failed for {len(invoices_failed)} location(s)" if invoices_failed else "",
            f"conditions failed for {len(conditions_failed)} location(s)"
            if conditions_failed
            else "",
        ]
        _finish(db, job, SyncJobStatus.partial, "; ".join(p for p in problems if p))
    else:
        _finish(db, job, SyncJobStatus.succeeded)
    return job


LOCATION_SYNC_KINDS = (SyncJobKind.bill_to_location_sync, SyncJobKind.location_sync)


def _run_location_sync(
    db: Session, job: SyncJob, client: PestPacClient, locations: list[Location]
) -> SyncJob:
    """ "Sync location": per location, its areas, its documents list, its conditions (which can
    add condition documents, and name their areas), then files not stored yet. Locations are
    independent; one failing (PestPac or storage unreachable) leaves the others' work."""
    area_totals = AreaSyncCounts()
    document_totals = DocumentSyncCounts()
    condition_totals = ConditionSyncCounts()
    failed: list[dict] = []
    progress: dict = {"locations_total": len(locations), "locations_done": 0}
    # Without object storage the lists still sync; files wait until it's configured.
    try:
        storage = get_storage()
    except StorageNotConfiguredError as exc:
        storage = None
        progress["document_files"] = str(exc)

    for done, location in enumerate(locations, start=1):
        area_counts = AreaSyncCounts()
        document_counts = DocumentSyncCounts()
        condition_counts = ConditionSyncCounts()
        lists_committed = False
        try:
            location_areas.sync_location_areas(db, client, location, area_counts)
            documents.sync_location_metadata(db, client, location, document_counts)
            conditions.sync_location_conditions(db, client, location, condition_counts)
            location_areas.link_conditions(db, location, area_counts)
            db.commit()
            lists_committed = True
            if storage is not None:
                documents.store_location_files(db, client, storage, location, document_counts)
        except (PestPacUnavailableError, StorageError) as exc:
            db.rollback()
            log.warning("Sync of location %s failed: %s", location.pestpac_location_id, exc)
            failed.append(
                {"pestpac_location_id": location.pestpac_location_id, "error": str(exc)[:300]}
            )
        # Lists count only if they were committed; files commit one by one, so they count even
        # if a later one stopped the location.
        if lists_committed:
            _add(area_totals, area_counts)
            _add(condition_totals, condition_counts)
            _add(document_totals, document_counts)
        else:
            document_totals.files_stored += document_counts.files_stored
        job = db.get(SyncJob, job.id)
        job.progress = {
            **progress,
            "locations_done": done,
            "failed_locations": failed,
            "areas": area_totals.model_dump(),
            "documents": document_totals.model_dump(),
            "conditions": condition_totals.model_dump(),
        }
        job.heartbeat_at = datetime.now(UTC)
        db.commit()

    if failed and len(failed) == len(locations):
        _finish(db, job, SyncJobStatus.failed, "Every location failed; see progress")
    elif failed:
        _finish(db, job, SyncJobStatus.partial, f"{len(failed)} location(s) failed")
    else:
        _finish(db, job, SyncJobStatus.succeeded)
    return job


def _add(total: BaseModel, counts: BaseModel) -> None:
    for field in type(total).model_fields:
        setattr(total, field, getattr(total, field) + getattr(counts, field))


def jobs_for_bill_to(
    db: Session, bill_to_id: uuid.UUID, *, location_id: uuid.UUID | None = None, limit: int = 10
) -> list[SyncJob]:
    """The bill-to's newest jobs. With `location_id`: the newest job of each kind covering that
    location (its own or bill-to-wide), since webhooks queue syncs for other locations faster
    than a plain newest-first list would reach this one's. Newest first either way."""
    if location_id is None:
        return list(
            db.scalars(
                select(SyncJob)
                .where(SyncJob.bill_to_id == bill_to_id)
                .order_by(SyncJob.created_at.desc())
                .limit(limit)
            )
        )
    latest = (
        select(SyncJob.id)
        .where(
            SyncJob.bill_to_id == bill_to_id,
            or_(SyncJob.location_id == location_id, SyncJob.location_id.is_(None)),
        )
        .order_by(SyncJob.kind, SyncJob.created_at.desc())
        .ext(distinct_on(SyncJob.kind))
    )
    return list(
        db.scalars(
            select(SyncJob).where(SyncJob.id.in_(latest)).order_by(SyncJob.created_at.desc())
        )
    )
