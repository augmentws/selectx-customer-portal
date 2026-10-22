import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import ServiceOrder
from app.schemas.tenancy import NoteRead, ServiceOrderRead
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import notes

router = APIRouter(prefix="/service-orders", tags=["service_orders"])


def _order_or_404(db: Session, order_id: uuid.UUID, scope: AccessScope) -> ServiceOrder:
    order = db.get(ServiceOrder, order_id, options=[selectinload(ServiceOrder.technician)])
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(Perm.bill_tos_read, order.operator_id, read_perm=Perm.bill_tos_read)
    return order


@router.get("/{order_id}", response_model=ServiceOrderRead)
def get_service_order(
    order_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    return _order_or_404(db, order_id, scope)


@router.get("/{order_id}/notes", response_model=list[NoteRead])
def list_notes(
    order_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Notes PestPac associates with this order (e.g. the technician's service notes)."""
    order = _order_or_404(db, order_id, scope)
    return notes.list_notes(db, service_order_id=order.id)
