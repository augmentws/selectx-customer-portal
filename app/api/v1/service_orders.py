import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import BillTo, InspectionFinding, Location, ServiceOrder
from app.schemas.tenancy import (
    InspectionFindingRead,
    NoteRead,
    ServiceOrderDetail,
    ServiceOrderRead,
    ServiceOrderRelated,
)
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import notes, order_related, service_reports, trail

router = APIRouter(prefix="/service-orders", tags=["service_orders"])


def _order_or_404(db: Session, order_id: uuid.UUID, scope: AccessScope) -> ServiceOrder:
    order = db.get(ServiceOrder, order_id, options=[selectinload(ServiceOrder.technician)])
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(Perm.bill_tos_read, order.operator_id, read_perm=Perm.bill_tos_read)
    return order


@router.get("/{order_id}", response_model=ServiceOrderDetail)
def get_service_order(
    order_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The order with its breadcrumb trail (down to its location), report, stored invoice,
    and findings."""
    order = _order_or_404(db, order_id, scope)
    bill_to = db.get(BillTo, order.bill_to_id)
    location = db.get(Location, order.location_id) if order.location_id else None
    finding = db.scalar(
        select(InspectionFinding).where(InspectionFinding.service_order_id == order.id)
    )
    return ServiceOrderDetail(
        **ServiceOrderRead.model_validate(order).model_dump(),
        location_name=trail.location_name(location) if location else None,
        report_id=service_reports.report_ids_for_orders(db, [order.id]).get(order.id),
        trail=trail.trail(
            db,
            operator_id=order.operator_id,
            company_id=bill_to.company_id,
            bill_to_id=bill_to.id,
            location_id=order.location_id,
        ),
        invoice_id=order_related.stored_invoice_id(db, order),
        findings=InspectionFindingRead.model_validate(finding) if finding else None,
    )


@router.get("/{order_id}/related", response_model=ServiceOrderRelated)
def list_related(
    order_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Documents, conditions (with inspections and photos), and notes logged around the
    order: those PestPac links to it, then its location's from within a day of the work
    date (`link` says which)."""
    order = _order_or_404(db, order_id, scope)
    return order_related.related(db, order)


@router.get("/{order_id}/notes", response_model=list[NoteRead])
def list_notes(
    order_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Notes PestPac associates with this order (e.g. the technician's service notes)."""
    order = _order_or_404(db, order_id, scope)
    return notes.list_notes(db, service_order_id=order.id)
