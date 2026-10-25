"""PestPac invoices: fetched by id (GET /Invoices/{id}) when an invoice webhook arrives, and by
order number (GET /Invoices?orderNumber=) for worked orders without one during order syncs.

Only invoices of an onboarded, active bill-to are stored. An invoice also completes its service
order: billed work drops off PestPac's open-orders list, so the invoice is our last chance to
learn its InvoiceID, that it was worked, and the technician's comment.
"""

import uuid
from datetime import UTC, datetime

import requests
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, selectinload

from app.integrations.pestpac import PestPacAuthError, PestPacClient
from app.models import BillTo, Invoice, InvoiceLine, Location, ServiceOrder
from app.schemas.pestpac import (
    InvoiceSyncCounts,
    PestPacInvoiceDetails,
    ServiceOrderSyncCounts,
)
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


def fetch_invoices_for_order(
    client: PestPacClient, order_number: str
) -> list[PestPacInvoiceDetails]:
    """The invoice for an order number (the full object, as GET /Invoices/{id}), or [] when
    PestPac answers 404: the order isn't invoiced yet."""
    try:
        response = client.custom_endpoint("/Invoices").get(params={"orderNumber": order_number})
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise PestPacUnavailableError(f"PestPac /Invoices search returned {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise PestPacUnavailableError("PestPac returned an unexpected invoice search response")
    # Only an exact match: don't trust the search to be exact.
    if str(body.get("OrderNumber") or "") != order_number:
        return []
    try:
        return [PestPacInvoiceDetails.from_api(body)]
    except ValueError as exc:
        raise PestPacUnavailableError(f"PestPac returned an unusable invoice: {exc}") from None


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


def upsert_invoice(
    db: Session,
    operator_id: uuid.UUID,
    details: PestPacInvoiceDetails,
    technicians: TechnicianResolver,
) -> Invoice | None:
    """Store the invoice if its bill-to is onboarded and active (None otherwise). Does not
    commit."""
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
    invoice = _find(db, operator_id, details.pestpac_invoice_id)
    if invoice is None:
        invoice = Invoice(operator_id=operator_id, pestpac_invoice_id=details.pestpac_invoice_id)
        db.add(invoice)
    for field in PestPacInvoiceDetails.model_fields:
        if field != "lines":
            setattr(invoice, field, getattr(details, field))
    invoice.bill_to_id = bill_to.id
    invoice.location_id = (
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
    invoice.service_order_id = order.id if order else None
    invoice.technician_id = technicians.resolve(details.pestpac_tech_id, ServiceOrderSyncCounts())
    invoice.lines = [
        InvoiceLine(position=n, **line.model_dump()) for n, line in enumerate(details.lines, 1)
    ]
    invoice.removed_at = None
    invoice.pestpac_fetched_at = now
    if order is not None:
        _complete_order(order, invoice, now)
    db.flush()
    return invoice


def sync_location_invoices(
    db: Session, client: PestPacClient, location: Location, technicians: TechnicianResolver
) -> InvoiceSyncCounts:
    """Fetch invoices for the location's worked orders that have none stored yet (billed or
    not: unbilled ones simply find nothing and are tried again next sync). Does not commit."""
    counts = InvoiceSyncCounts()
    orders = db.scalars(
        select(ServiceOrder)
        .where(
            ServiceOrder.location_id == location.id,
            ServiceOrder.posted.is_(True),
            ServiceOrder.order_number.is_not(None),
            ~exists().where(Invoice.service_order_id == ServiceOrder.id),
        )
        .order_by(ServiceOrder.work_date, ServiceOrder.id)
    ).all()
    for order in orders:
        counts.orders_checked += 1
        found = fetch_invoices_for_order(client, order.order_number)
        if not found:
            counts.not_invoiced += 1
        for details in found:
            if upsert_invoice(db, location.operator_id, details, technicians) is not None:
                counts.stored += 1
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
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Invoice], int]:
    """Invoices with their lines, technician, location, and service order (with its
    technician). Newest first by invoice date."""
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
        .order_by(Invoice.invoice_date.desc().nulls_last(), Invoice.pestpac_invoice_id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total
