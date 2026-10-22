import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Location
from app.schemas.tenancy import LocationRead, NoteRead, ServiceOrderRead, SyncJobRead
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import notes, service_orders, sync_jobs

router = APIRouter(prefix="/locations", tags=["locations"])


def _location_or_404(db: Session, location_id: uuid.UUID) -> Location:
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return location


@router.get("/{location_id}", response_model=LocationRead)
def get_location(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    counts = service_orders.open_order_counts(db, [location.id])
    return LocationRead.model_validate(location).model_copy(
        update={"open_order_count": counts.get(location.id, 0)}
    )


@router.get("/{location_id}/notes", response_model=list[NoteRead])
def list_notes(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The location's full PestPac note history, newest first."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return notes.list_notes(db, location_id=location.id)


@router.get("/{location_id}/service-orders", response_model=list[ServiceOrderRead])
def list_service_orders(
    location_id: uuid.UUID,
    status: Literal["open", "closed", "all"] = "open",
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return service_orders.list_orders(db, location_id=location.id, status=status)


@router.post(
    "/{location_id}/service-orders/sync",
    response_model=SyncJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def sync_service_orders(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_write, location.operator_id, read_perm=Perm.bill_tos_read)
    if location.removed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PestPac no longer lists this location under its bill-to",
        )
    job = sync_jobs.enqueue_location(db, location, requested_by=scope.user_id)
    db.commit()
    return job
