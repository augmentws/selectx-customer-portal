import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1._pestpac_errors import pestpac_errors
from app.db.session import get_db
from app.models import BillTo
from app.schemas.tenancy import BillToRead, BillToUpdate
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import tenancy

router = APIRouter(prefix="/bill-tos", tags=["bill_tos"])


def _bill_to_or_404(db: Session, bill_to_id: uuid.UUID) -> BillTo:
    bill_to = db.get(BillTo, bill_to_id)
    if bill_to is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return bill_to


@router.get("/{bill_to_id}", response_model=BillToRead)
def get_bill_to(
    bill_to_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_read, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    return bill_to


@router.patch("/{bill_to_id}", response_model=BillToRead)
def update_bill_to(
    bill_to_id: uuid.UUID,
    data: BillToUpdate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_write, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    return tenancy.update_bill_to(db, bill_to, data)


@router.post("/{bill_to_id}/refresh", response_model=BillToRead)
def refresh_bill_to(
    bill_to_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Re-fetch identifying details from PestPac."""
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_write, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    with pestpac_errors():
        return tenancy.refresh_bill_to(db, bill_to)
