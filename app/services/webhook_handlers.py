"""Processing stored PestPac webhook events (run by the worker).

Service orders and invoices have handlers; other entities' events stay `received`.

Invoice events: PestPac sends an invoice's create and updates seconds apart, so they wait
(`INVOICE_WEBHOOK_WAIT_MINUTES` after the invoice's first waiting event, or until
`INVOICE_WEBHOOK_MAX_UPDATES` updates arrive) and then share one GET /Invoices/{id}. The invoice
is stored if its bill-to is onboarded (see `invoices`), and so is its order when we don't hold it
(billed before we heard of it). A delete flags our copy removed straight away, with no call.

A service order event doesn't write the order from its body: it queues the order's location
for the usual service-order sync, which re-reads PestPac, applies the field whitelist and
bill-to rule, marks the order worked, and collects the location's notes and invoices.
Signatures are only reported for now, so the body isn't trusted beyond choosing what to sync.
An event for a location that's already queued or syncing shares that job. Billed orders, which
PestPac no longer lists, arrive through their invoice events instead.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, tuple_, update
from sqlalchemy.orm import Session, aliased

from app.core.config import get_settings
from app.models import (
    BillTo,
    Invoice,
    Location,
    ServiceOrder,
    SyncJob,
    Tenant,
    WebhookEntity,
    WebhookEvent,
    WebhookEventStatus,
)
from app.schemas.pestpac import NoteSyncCounts
from app.services import invoices, notes, pestpac_connection, sync_jobs
from app.services.pestpac_connection import ConnectionNotReadyError, PestPacUnavailableError
from app.services.technicians import TechnicianResolver

HANDLED = (WebhookEntity.service_order, WebhookEntity.invoice)


def _invoices_ready():
    """(operator, InvoiceID) pairs whose waiting events may be fetched now."""
    settings = get_settings()
    w = aliased(WebhookEvent)
    return (
        select(w.operator_id, w.pestpac_entity_id)
        .where(w.entity == WebhookEntity.invoice, w.status == WebhookEventStatus.received)
        .group_by(w.operator_id, w.pestpac_entity_id)
        .having(
            or_(
                func.min(w.received_at)
                <= func.now() - timedelta(minutes=settings.invoice_webhook_wait_minutes),
                func.count().filter(w.action == "update") >= settings.invoice_webhook_max_updates,
            )
        )
    )


def claim_next(db: Session) -> WebhookEvent | None:
    """The oldest unprocessed event we can handle now, locked for this worker. Invoice events
    wait for their invoice's batch (deletes don't)."""
    ready = or_(
        WebhookEvent.entity == WebhookEntity.service_order,
        WebhookEvent.action == "delete",
        tuple_(WebhookEvent.operator_id, WebhookEvent.pestpac_entity_id).in_(_invoices_ready()),
    )
    return db.scalar(
        select(WebhookEvent)
        .where(
            WebhookEvent.status == WebhookEventStatus.received,
            WebhookEvent.entity.in_(HANDLED),
            ready,
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


def _waiting_invoice_events(db: Session, event: WebhookEvent) -> list[WebhookEvent]:
    """The invoice's other waiting events (not deletes), locked: one fetch answers them all."""
    return list(
        db.scalars(
            select(WebhookEvent)
            .where(
                WebhookEvent.operator_id == event.operator_id,
                WebhookEvent.entity == WebhookEntity.invoice,
                WebhookEvent.pestpac_entity_id == event.pestpac_entity_id,
                WebhookEvent.status == WebhookEventStatus.received,
                WebhookEvent.action != "delete",
                WebhookEvent.id != event.id,
            )
            .with_for_update(skip_locked=True)
        )
    )


def _process_invoice(db: Session, event: WebhookEvent, batch: list[WebhookEvent]) -> str | None:
    """Fetch and store the invoice (and its order, if we don't hold it) once for the batch;
    returns an error message, or None."""
    if event.action == "delete":
        invoices.mark_removed(db, event.operator_id, event.pestpac_entity_id)
        return None
    stored = db.scalar(
        select(Invoice).where(
            Invoice.operator_id == event.operator_id,
            Invoice.pestpac_invoice_id == event.pestpac_entity_id,
        )
    )
    if stored is not None and stored.pestpac_fetched_at >= max(e.received_at for e in batch):
        return None  # fetched after these events arrived: our copy already reflects them
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
    invoice = invoices.upsert_invoice(
        db,
        event.operator_id,
        details,
        TechnicianResolver(db, client, event.operator_id),
        create_order=True,
    )
    if invoice is not None and invoice.service_order_id is not None:
        notes.link_notes_to_orders(db, event.operator_id, NoteSyncCounts())
    return None


def process(db: Session, event: WebhookEvent) -> None:
    """Handle one event (an invoice event with its batch). Does not commit."""
    now = datetime.now(UTC)
    if event.entity is WebhookEntity.invoice:
        batch = [event]
        if event.action != "delete":
            batch += _waiting_invoice_events(db, event)
        error = _process_invoice(db, event, batch)
        for e in batch:
            e.status = WebhookEventStatus.failed if error else WebhookEventStatus.processed
            e.error = error
            e.processed_at = now
        db.flush()
        return
    if event.entity is not WebhookEntity.service_order:
        raise ValueError(f"No handler for {event.entity} events")
    if event.action == "delete":
        # Orders are never deleted, so there's nothing to do.
        event.status = WebhookEventStatus.processed
    else:
        job, error = _queue_sync(db, event)
        event.sync_job_id = job.id if job else None
        event.status = WebhookEventStatus.failed if error else WebhookEventStatus.processed
        event.error = error
    event.processed_at = now
    db.flush()


def requeue_failed_invoices(db: Session) -> int:
    """Send failed invoice events whose invoice we still don't hold back to the worker (e.g.
    after PestPac refused us for a while). They're fetched again, one call per invoice. Commits;
    returns how many were requeued."""
    held = (
        select(Invoice.id)
        .where(
            Invoice.operator_id == WebhookEvent.operator_id,
            Invoice.pestpac_invoice_id == WebhookEvent.pestpac_entity_id,
        )
        .exists()
    )
    result = db.execute(
        update(WebhookEvent)
        .where(
            WebhookEvent.entity == WebhookEntity.invoice,
            WebhookEvent.action != "delete",
            WebhookEvent.status == WebhookEventStatus.failed,
            ~held,
        )
        .values(status=WebhookEventStatus.received, error=None, processed_at=None)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount or 0


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
