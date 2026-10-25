"""Processing stored PestPac webhook events (run by the worker).

Service orders and invoices have handlers; other entities' events stay `received`.

An invoice event fetches GET /Invoices/{id} and stores it if its bill-to is onboarded (see
`invoices`); a delete flags our copy removed.

A service order event doesn't write the order from its body: it queues the order's location
for the usual service-order sync, which re-reads PestPac, applies the field whitelist and
bill-to rule, marks the order worked, and collects the location's notes. Signatures are only
reported for now, so the body isn't trusted beyond choosing what to sync. An event for a
location that's already queued or syncing shares that job.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    BillTo,
    Location,
    ServiceOrder,
    SyncJob,
    Tenant,
    WebhookEntity,
    WebhookEvent,
    WebhookEventStatus,
)
from app.services import invoices, pestpac_connection, sync_jobs
from app.services.pestpac_connection import ConnectionNotReadyError, PestPacUnavailableError
from app.services.technicians import TechnicianResolver

HANDLED = (WebhookEntity.service_order, WebhookEntity.invoice)


def claim_next(db: Session) -> WebhookEvent | None:
    """The oldest unprocessed event we have a handler for, locked for this worker."""
    return db.scalar(
        select(WebhookEvent)
        .where(
            WebhookEvent.status == WebhookEventStatus.received,
            WebhookEvent.entity.in_(HANDLED),
        )
        .order_by(WebhookEvent.received_at, WebhookEvent.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def _order_location(db: Session, event: WebhookEvent) -> Location | None:
    """The body's LocationID (the order may have moved), else the location of our copy."""
    if event.pestpac_location_id is not None:
        location = db.scalar(
            select(Location).where(
                Location.operator_id == event.operator_id,
                Location.pestpac_location_id == event.pestpac_location_id,
                Location.removed_at.is_(None),
            )
        )
        if location is not None:
            return location
    order = db.scalar(
        select(ServiceOrder).where(
            ServiceOrder.operator_id == event.operator_id,
            ServiceOrder.pestpac_order_id == event.pestpac_entity_id,
        )
    )
    if order is None or order.location_id is None:
        return None
    return db.get(Location, order.location_id)


def _queue_sync(db: Session, event: WebhookEvent) -> tuple[SyncJob | None, str | None]:
    """The job to run for an order event, or why there is none (an error message)."""
    location = _order_location(db, event)
    if location is not None:
        bill_to = db.get(BillTo, location.bill_to_id)
        if not bill_to.is_active:
            return None, None  # orders of inactive bill-tos aren't synced
        return sync_jobs.enqueue_location(db, location, None), None
    # A location we haven't synced yet (e.g. new): the bill-to sync refreshes its locations.
    if event.pestpac_bill_to_id is not None:
        bill_to = db.scalar(
            select(BillTo).where(
                BillTo.operator_id == event.operator_id,
                BillTo.pestpac_bill_to_id == event.pestpac_bill_to_id,
            )
        )
        if bill_to is not None:
            if not bill_to.is_active:
                return None, None
            return sync_jobs.enqueue_bill_to(db, bill_to, None), None
    return None, "No synced location or onboarded bill-to for this order"


def _process_invoice(db: Session, event: WebhookEvent) -> str | None:
    """Fetch and store the invoice; returns an error message, or None."""
    if event.action == "delete":
        invoices.mark_removed(db, event.operator_id, event.pestpac_entity_id)
        return None
    operator = db.get(Tenant, event.operator_id)
    try:
        client = pestpac_connection.get_pestpac_client(db, operator)
        details = invoices.fetch_invoice(client, event.pestpac_entity_id)
    except (ConnectionNotReadyError, PestPacUnavailableError) as exc:
        return str(exc)
    if details is None:
        if invoices.mark_removed(db, event.operator_id, event.pestpac_entity_id):
            return None
        return "Invoice not found in PestPac"
    # Not stored when its bill-to isn't onboarded and active: nothing more to do.
    invoices.upsert_invoice(
        db, event.operator_id, details, TechnicianResolver(db, client, event.operator_id)
    )
    return None


def process(db: Session, event: WebhookEvent) -> None:
    """Handle one event. Does not commit."""
    now = datetime.now(UTC)
    if event.entity is WebhookEntity.invoice:
        error = _process_invoice(db, event)
        event.status = WebhookEventStatus.failed if error else WebhookEventStatus.processed
        event.error = error
    elif event.entity is not WebhookEntity.service_order:
        raise ValueError(f"No handler for {event.entity} events")
    elif event.action == "delete":
        # Orders are never deleted, so there's nothing to do.
        event.status = WebhookEventStatus.processed
    else:
        job, error = _queue_sync(db, event)
        event.sync_job_id = job.id if job else None
        event.status = WebhookEventStatus.failed if error else WebhookEventStatus.processed
        event.error = error
    event.processed_at = now
    db.flush()


def mark_crashed(db: Session, event_id: uuid.UUID, error: str) -> None:
    """Record a handler bug on the event so it isn't retried in a loop. Commits."""
    db.execute(
        update(WebhookEvent)
        .where(WebhookEvent.id == event_id)
        .values(
            status=WebhookEventStatus.failed, error=error[:1000], processed_at=datetime.now(UTC)
        )
    )
    db.commit()
