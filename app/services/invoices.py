"""PestPac invoices: fetched by id (GET /Invoices/{id}) when an invoice webhook arrives, and during
order syncs for each invoice in the location's service history (GET
/Locations/{id}/serviceHistory) that we don't hold yet.

Only invoices of an onboarded, active bill-to are stored. An invoice also completes its service
order: billed work drops off PestPac's open-orders list, so the invoice is our last chance to
learn its InvoiceID, that it was worked, and the technician's comment.
"""

import uuid
from datetime import UTC, datetime

import requests
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.integrations.pestpac import PestPacAuthError, PestPacClient
from app.models import BillTo, Invoice, InvoiceLine, Location, ServiceOrder
from app.schemas.pestpac import (
    InvoiceSyncCounts,
    NoteSyncCounts,
    PestPacInvoiceDetails,
    ServiceOrderSyncCounts,
)
from app.services import findings_extraction, notes
from app.services.pestpac_connection import PestPacUnavailableError
from app.services.technicians import TechnicianResolver


def fetch_invoice(client: PestPacClient, pestpac_invoice_id: int) -> PestPacInvoiceDetails | None:
    """The invoice, or None if PestPac has no such InvoiceID."""
    try:
        response = client.custom_endpoint(f"/Invoices/{pestpac_invoice_id}").get()
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise PestPacUnavailableError(f"PestPac /Invoices returned {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("InvoiceID") != pestpac_invoice_id:
        raise PestPacUnavailableError("PestPac returned an unexpected invoice response")
    try:
        return PestPacInvoiceDetails.from_api(body)
    except ValueError as exc:
        raise PestPacUnavailableError(f"PestPac returned an unusable invoice: {exc}") from None


def fetch_service_history(client: PestPacClient, pestpac_location_id: int) -> list[dict]:
    """Every invoice PestPac lists for the location: summaries (no line items, instructions, or
    technician comment), each with its InvoiceID, OrderID, and LocationID. Pages with skip/top,
    like notes; a short page ends paging."""
    settings = get_settings()
    top = settings.pestpac_page_size
    path = f"/Locations/{pestpac_location_id}/serviceHistory"
    by_id: dict[int, dict] = {}
    for page_number in range(settings.pestpac_max_pages):
        try:
            response = client.custom_endpoint(path).get(
                params={"skip": page_number * top, "top": top}
            )
        except (PestPacAuthError, requests.RequestException) as exc:
            raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise PestPacUnavailableError(f"PestPac {path} returned {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, list) or not all(
            isinstance(e, dict) and isinstance(e.get("InvoiceID"), int) for e in body
        ):
            raise PestPacUnavailableError("PestPac returned an unexpected service history response")
        if body and body[0]["InvoiceID"] in by_id:
            raise PestPacUnavailableError(
                "PestPac returned the same page of service history twice; paging is not advancing"
            )
        by_id.update({e["InvoiceID"]: e for e in body})
        if len(body) < top:
            return list(by_id.values())
    raise PestPacUnavailableError(
        f"Location {pestpac_location_id} has more than {settings.pestpac_max_pages * top} "
        "invoices; raise PESTPAC_MAX_PAGES to sync them"
    )


def _find(db: Session, operator_id: uuid.UUID, pestpac_invoice_id: int) -> Invoice | None:
    return db.scalar(
        select(Invoice).where(
            Invoice.operator_id == operator_id, Invoice.pestpac_invoice_id == pestpac_invoice_id
        )
    )


def _complete_order(order: ServiceOrder, invoice: Invoice, now: datetime) -> None:
    """What the invoice tells us about its order, without overwriting what we already know."""
    if order.pestpac_invoice_id is None:
        order.pestpac_invoice_id = invoice.pestpac_invoice_id
    if not order.posted:  # worked and billed between two of our syncs
        order.posted = True
        order.posted_at = order.posted_at or now
    if order.technician_comment is None and invoice.technician_comment:
        order.technician_comment = invoice.technician_comment


def _order_from_invoice(
    db: Session,
    operator_id: uuid.UUID,
    details: PestPacInvoiceDetails,
    bill_to_id: uuid.UUID,
    location_id: uuid.UUID | None,
    technician_id: uuid.UUID | None,
    now: datetime,
) -> ServiceOrder:
    """Our copy of an order PestPac no longer lists: once billed, only its invoice remains. It
    carries the order's id, number, service, work date, position-1 technician, instructions, and
    technician comment; Tech1's username isn't on the invoice.

    Inserted with ON CONFLICT DO NOTHING, then read back: another worker handling another event
    for the same order may store it first, and then that copy is used."""
    db.execute(
        pg_insert(ServiceOrder)
        .values(
            id=uuid.uuid4(),
            operator_id=operator_id,
            bill_to_id=bill_to_id,
            location_id=location_id,
            pestpac_order_id=details.pestpac_order_id,
            pestpac_location_id=details.pestpac_location_id,
            order_number=details.order_number,
            service_code=details.service_code,
            description=details.description,
            work_date=details.work_date,
            tech_id=details.pestpac_tech_id,
            technician_id=technician_id,
            location_instructions=details.location_instructions,
            service_instructions=details.service_instructions,
            order_instructions=details.order_instructions,
            technician_comment=details.technician_comment,
            pestpac_invoice_id=details.pestpac_invoice_id,
            posted=True,
            posted_at=now,
            closed_at=now,
            pestpac_fetched_at=now,
        )
        .on_conflict_do_nothing(index_elements=["operator_id", "pestpac_order_id"])
    )
    return db.scalars(
        select(ServiceOrder).where(
            ServiceOrder.operator_id == operator_id,
            ServiceOrder.pestpac_order_id == details.pestpac_order_id,
        )
    ).one()


def upsert_invoice(
    db: Session,
    operator_id: uuid.UUID,
    details: PestPacInvoiceDetails,
    technicians: TechnicianResolver,
    *,
    create_order: bool = False,
) -> Invoice | None:
    """Store the invoice if its bill-to is onboarded and active (None otherwise). Does not
    commit.

    `create_order`: when we don't hold the invoice's order, store it from the invoice as worked
    and billed (for orders PestPac had already billed when we heard of them)."""
    bill_to = db.scalar(
        select(BillTo).where(
            BillTo.operator_id == operator_id,
            BillTo.pestpac_bill_to_id == details.pestpac_bill_to_id,
            BillTo.is_active.is_(True),
        )
    )
    if bill_to is None:
        return None
    now = datetime.now(UTC)
    # Before the invoice joins the session: resolving may store a technician and flush.
    technician_id = technicians.resolve(details.pestpac_tech_id, ServiceOrderSyncCounts())
    location_id = (
        db.scalar(
            select(Location.id).where(
                Location.operator_id == operator_id,
                Location.pestpac_location_id == details.pestpac_location_id,
            )
        )
        if details.pestpac_location_id is not None
        else None
    )
    order = (
        db.scalar(
            select(ServiceOrder).where(
                ServiceOrder.operator_id == operator_id,
                ServiceOrder.pestpac_order_id == details.pestpac_order_id,
            )
        )
        if details.pestpac_order_id is not None
        else None
    )
    was_posted = order is not None and order.posted
    if (
        order is None
        and create_order
        and details.pestpac_order_id is not None
        and details.pestpac_location_id is not None
    ):
        order = _order_from_invoice(
            db, operator_id, details, bill_to.id, location_id, technician_id, now
        )
    invoice = _find(db, operator_id, details.pestpac_invoice_id)
    if invoice is None:
        invoice = Invoice(operator_id=operator_id, pestpac_invoice_id=details.pestpac_invoice_id)
        db.add(invoice)
    for field in PestPacInvoiceDetails.model_fields:
        if field != "lines":
            setattr(invoice, field, getattr(details, field))
    invoice.bill_to_id = bill_to.id
    invoice.location_id = location_id
    invoice.technician_id = technician_id
    invoice.service_order_id = order.id if order else None
    invoice.lines = [
        InvoiceLine(position=n, **line.model_dump()) for n, line in enumerate(details.lines, 1)
    ]
    invoice.removed_at = None
    invoice.pestpac_fetched_at = now
    if order is not None:
        _complete_order(order, invoice, now)
        if not was_posted:  # worked and billed between our syncs, or new to us
            findings_extraction.request_if_enabled(db, order, bill_to.company_id)
    db.flush()
    return invoice


def sync_location_invoices(
    db: Session, client: PestPacClient, location: Location, technicians: TechnicianResolver
) -> InvoiceSyncCounts:
    """Store every invoice in the location's service history that we don't hold yet (GET
    /Invoices/{id} for each: the history leaves out line items and the technician comment).
    An order we don't hold is stored from its invoice, as worked and billed: RAMP program nights
    are billed before an order sync ever sees them. Then worked orders without an invoice are
    linked to one we hold for their OrderID (from a webhook, before we held the order), with no
    call. Does not commit."""
    counts = InvoiceSyncCounts()
    operator_id = location.operator_id
    history = fetch_service_history(client, location.pestpac_location_id)
    counts.listed = len(history)
    held = set(
        db.scalars(
            select(Invoice.pestpac_invoice_id).where(
                Invoice.operator_id == operator_id,
                Invoice.pestpac_invoice_id.in_([e["InvoiceID"] for e in history]),
            )
        )
    )
    known_orders = set(
        db.scalars(
            select(ServiceOrder.pestpac_order_id).where(
                ServiceOrder.operator_id == operator_id,
                ServiceOrder.pestpac_order_id.in_(
                    [e["OrderID"] for e in history if isinstance(e.get("OrderID"), int)]
                ),
            )
        )
    )
    for entry in sorted(history, key=lambda e: e["InvoiceID"]):
        if entry["InvoiceID"] in held:
            counts.held += 1
            continue
        details = fetch_invoice(client, entry["InvoiceID"])
        if details is None:  # removed between the two calls
            counts.not_found += 1
            continue
        invoice = upsert_invoice(db, operator_id, details, technicians, create_order=True)
        if invoice is None:  # not an onboarded, active bill-to
            continue
        counts.stored += 1
        order_id = details.pestpac_order_id
        if order_id is not None and order_id not in known_orders and invoice.service_order_id:
            counts.orders_created += 1
            known_orders.add(order_id)

    now = datetime.now(UTC)
    unlinked = db.scalars(
        select(ServiceOrder).where(
            ServiceOrder.location_id == location.id,
            ServiceOrder.posted.is_(True),
            ~exists().where(Invoice.service_order_id == ServiceOrder.id),
        )
    ).all()
    for order in unlinked:
        invoice = db.scalar(
            select(Invoice).where(
                Invoice.operator_id == operator_id,
                Invoice.pestpac_order_id == order.pestpac_order_id,
                Invoice.removed_at.is_(None),
            )
        )
        if invoice is not None:
            invoice.service_order_id = order.id
            _complete_order(order, invoice, now)
            counts.linked += 1
    if counts.orders_created:
        # Their notes are already stored (a location's whole note history is synced).
        notes.link_notes_to_orders(db, operator_id, NoteSyncCounts())
    db.flush()
    return counts


def mark_removed(db: Session, operator_id: uuid.UUID, pestpac_invoice_id: int) -> bool:
    """Flag an invoice PestPac deleted (rows are never deleted). Does not commit."""
    invoice = _find(db, operator_id, pestpac_invoice_id)
    if invoice is None:
        return False
    invoice.removed_at = invoice.removed_at or datetime.now(UTC)
    db.flush()
    return True


def list_invoices(
    db: Session,
    *,
    location_id: uuid.UUID | None = None,
    bill_to_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    newest_first: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Invoice], int]:
    """Invoices with their lines, technician, location, and service order (with its
    technician), by invoice date: newest first unless `newest_first` is false; undated last."""
    query = select(Invoice)
    if location_id is not None:
        query = query.where(Invoice.location_id == location_id)
    if bill_to_id is not None:
        query = query.where(Invoice.bill_to_id == bill_to_id)
    if company_id is not None:
        query = query.where(
            Invoice.bill_to_id.in_(select(BillTo.id).where(BillTo.company_id == company_id))
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.options(
            selectinload(Invoice.lines),
            selectinload(Invoice.technician),
            selectinload(Invoice.location),
            selectinload(Invoice.service_order).selectinload(ServiceOrder.technician),
        )
        .order_by(
            *(
                (Invoice.invoice_date.desc().nulls_last(), Invoice.pestpac_invoice_id.desc())
                if newest_first
                else (Invoice.invoice_date.asc().nulls_last(), Invoice.pestpac_invoice_id.asc())
            )
        )
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total
