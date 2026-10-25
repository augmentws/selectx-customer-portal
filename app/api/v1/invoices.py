import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import BillTo, Company, Invoice, Location
from app.schemas.invoices import InvoicedOrderPage, InvoicedOrderRead, InvoicePage, InvoiceRead
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import invoices

router = APIRouter(tags=["invoices"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("/locations/{location_id}/invoices", response_model=InvoicePage)
def list_location_invoices(
    location_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """The location's invoices (from invoice webhooks), newest first. Billing data: needs
    billing:read."""
    location = db.get(Location, location_id)
    if location is None:
        raise _not_found()
    scope.require(Perm.billing_read, location.operator_id, read_perm=Perm.bill_tos_read)
    rows, total = invoices.list_invoices(db, location_id=location.id, limit=limit, offset=offset)
    return InvoicePage(
        items=[InvoiceRead.model_validate(i) for i in rows], total=total, limit=limit, offset=offset
    )


@router.get("/invoices/{invoice_id}", response_model=InvoiceRead)
def get_invoice(
    invoice_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise _not_found()
    scope.require(Perm.billing_read, invoice.operator_id, read_perm=Perm.bill_tos_read)
    return invoice


def _invoiced_order_page(
    rows: list[Invoice], total: int, limit: int, offset: int
) -> InvoicedOrderPage:
    items = [
        InvoicedOrderRead.model_validate(
            InvoiceRead.model_validate(i).model_dump()
            | {
                "location_name": i.location.pestpac_company if i.location else None,
                "service_order": i.service_order,
            }
        )
        for i in rows
    ]
    return InvoicedOrderPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/bill-tos/{bill_to_id}/invoiced-orders", response_model=InvoicedOrderPage)
def list_bill_to_invoiced_orders(
    bill_to_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """The bill-to's invoices, newest first, each with the service order it bills."""
    bill_to = db.get(BillTo, bill_to_id)
    if bill_to is None:
        raise _not_found()
    scope.require(Perm.billing_read, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    rows, total = invoices.list_invoices(db, bill_to_id=bill_to.id, limit=limit, offset=offset)
    return _invoiced_order_page(rows, total, limit, offset)


@router.get("/companies/{company_id}/invoiced-orders", response_model=InvoicedOrderPage)
def list_company_invoiced_orders(
    company_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Invoices across all the company's bill-tos, newest first, each with its service order."""
    company = db.get(Company, company_id)
    if company is None:
        raise _not_found()
    scope.require(Perm.billing_read, company.operator_id, read_perm=Perm.companies_read)
    rows, total = invoices.list_invoices(db, company_id=company.id, limit=limit, offset=offset)
    return _invoiced_order_page(rows, total, limit, offset)
