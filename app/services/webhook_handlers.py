"""Processing stored PestPac webhook events (run by the worker).

Service orders and invoices have handlers; other entities' events stay `received`.

An invoice event fetches GET /Invoices/{id} and stores it if its bill-to is onboarded (see
`invoices`); a delete flags our copy removed.

A service order event doesn't write the order from its body: it queues the order's location
for the usual service-order sync, which re-reads PestPac, applies the field whitelist and
bill-to rule, marks the order worked, and collects the location's notes. Signatures are only
reported for now, so the body isn't trusted beyond choosing what to sync. An event for a
location that's already queued or syncing shares that job.

That sync only sees orders PestPac still lists, and a billed order is gone from PestPac: only
its invoice remains. So an event for an order we don't hold also searches its invoice by the
body's OrderNumber; an invoice for that OrderID stores both, the order as worked and billed
(`invoices.upsert_invoice(create_order=True)`), and links the order's notes. No invoice means
the order is still open, and the sync stores it.
"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import cast, select, update
from sqlalchemy.dialects.postgresql import JSONB
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
from app.schemas.pestpac import NoteSyncCounts
from app.services import invoices, notes, pestpac_connection, sync_jobs
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


def _held(db: Session, event: WebhookEvent) -> bool:
    return (
        db.scalar(
            select(ServiceOrder.id).where(
                ServiceOrder.operator_id == event.operator_id,
                ServiceOrder.pestpac_order_id == event.pestpac_entity_id,
            )
        )
        is not None
    )


def _body_order_number(event: WebhookEvent) -> str | None:
    """The OrderNumber in the event's body, used only to look the invoice up (the invoice must
    then name this event's OrderID). None once the raw body is purged."""
    if event.raw_body is None:
        return None
    try:
        body = json.loads(event.raw_body).get("EntityBody")
    except ValueError, AttributeError:
        return None
    value = body.get("OrderNumber") if isinstance(body, dict) else None
    if value is None:
        return None
    return str(value).strip() or None


def _store_billed_order(db: Session, event: WebhookEvent) -> str | None:
    """For an order we don't hold: store it from its invoice if it's already billed. Returns
    an error message, or None (including when there's no invoice: the order is still open)."""
    if _held(db, event):
        return None
    order_number = _body_order_number(event)
    if order_number is None:
        return None
    operator = db.get(Tenant, event.operator_id)
    try:
        client = pestpac_connection.get_pestpac_client(db, operator)
        found = invoices.fetch_invoices_for_order(client, order_number)
    except (ConnectionNotReadyError, PestPacUnavailableError) as exc:
        return f"Could not check whether the order is billed: {exc}"
    technicians = TechnicianResolver(db, client, event.operator_id)
    for details in found:
        if details.pestpac_order_id == event.pestpac_entity_id:
            invoices.upsert_invoice(db, event.operator_id, details, technicians, create_order=True)
            notes.link_notes_to_orders(db, event.operator_id, NoteSyncCounts())
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
        if job is not None:
            error = _store_billed_order(db, event)
        event.sync_job_id = job.id if job else None
        event.status = WebhookEventStatus.failed if error else WebhookEventStatus.processed
        event.error = error
    event.processed_at = now
    db.flush()


def requeue_unstored_orders(db: Session) -> int:
    """Send handled service order events whose order we still don't hold back to the worker
    (e.g. billed orders handled before invoices could fill them in). Only events that still
    have their body can be looked up. Commits; returns how many were requeued."""
    held = (
        select(ServiceOrder.id)
        .where(
            ServiceOrder.operator_id == WebhookEvent.operator_id,
            ServiceOrder.pestpac_order_id == WebhookEvent.pestpac_entity_id,
        )
        .exists()
    )
    result = db.execute(
        update(WebhookEvent)
        .where(
            WebhookEvent.entity == WebhookEntity.service_order,
            WebhookEvent.action != "delete",
            WebhookEvent.status.in_([WebhookEventStatus.processed, WebhookEventStatus.failed]),
            # Bodies were valid JSON when received; only those naming an order number can be
            # looked up.
            cast(WebhookEvent.raw_body, JSONB)["EntityBody"]["OrderNumber"].is_not(None),
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
