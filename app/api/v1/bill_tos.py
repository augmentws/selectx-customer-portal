import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1._pestpac_errors import pestpac_errors
from app.db.session import get_db
from app.models import BillTo
from app.schemas.pestpac import LocationSyncSummary
from app.schemas.tenancy import BillToRead, BillToSynced, BillToUpdate, LocationRead
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import locations, tenancy

router = APIRouter(prefix="/bill-tos", tags=["bill_tos"])


def bill_to_reads(db: Session, bill_tos: list[BillTo]) -> list[BillToRead]:
    counts = locations.location_counts(db, [b.id for b in bill_tos])
    return [
        BillToRead.model_validate(b).model_copy(update={"location_count": counts.get(b.id, 0)})
        for b in bill_tos
    ]


def bill_to_synced(db: Session, bill_to: BillTo, summary: LocationSyncSummary) -> BillToSynced:
    read = bill_to_reads(db, [bill_to])[0]
    return BillToSynced(**read.model_dump(), locations_sync=summary)


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
    return bill_to_reads(db, [bill_to])[0]


@router.patch("/{bill_to_id}", response_model=BillToRead)
def update_bill_to(
    bill_to_id: uuid.UUID,
    data: BillToUpdate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_write, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    return bill_to_reads(db, [tenancy.update_bill_to(db, bill_to, data)])[0]


@router.post("/{bill_to_id}/refresh", response_model=BillToSynced)
def refresh_bill_to(
    bill_to_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Re-fetch the bill-to's details and locations from PestPac."""
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_write, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    with pestpac_errors():
        bill_to, summary = tenancy.refresh_bill_to(db, bill_to)
    return bill_to_synced(db, bill_to, summary)


@router.get("/{bill_to_id}/locations", response_model=list[LocationRead])
def list_locations(
    bill_to_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Service locations synced from PestPac, current ones first."""
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_read, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    return locations.list_locations(db, bill_to.id)
