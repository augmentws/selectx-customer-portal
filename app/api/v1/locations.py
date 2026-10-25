import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Location, SyncJobKind
from app.schemas.tenancy import (
    ConditionBase,
    ConditionRead,
    DocumentRead,
    LocationRead,
    NoteRead,
    ServiceOrderRead,
    SyncJobRead,
)
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import conditions, documents, notes, service_orders, sync_jobs

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


@router.get("/{location_id}/documents", response_model=list[DocumentRead])
def list_documents(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Documents PestPac lists for the location (from PESTPAC_DOCUMENTS_START_DATE), newest
    first. Files are fetched with GET /v1/documents/{id}/file once stored."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return documents.list_documents(db, location_id=location.id)


@router.get("/{location_id}/conditions", response_model=list[ConditionRead])
def list_conditions(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The location's PestPac conditions (issues), open first, with inspections and
    documents. Filled by "Sync location"."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    rows = conditions.list_conditions(db, location_id=location.id)
    docs = conditions.documents_by_condition(db, [c.id for c in rows])
    return [
        ConditionRead(
            **ConditionBase.model_validate(c).model_dump(),
            documents=[DocumentRead.model_validate(d) for d in docs.get(c.id, [])],
        )
        for c in rows
    ]


@router.get("/{location_id}/service-orders", response_model=list[ServiceOrderRead])
def list_service_orders(
    location_id: uuid.UUID,
    status: Literal["open", "closed", "all"] = "open",
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return service_orders.list_orders(db, location_id=location.id, status=status, oldest_first=True)


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


@router.post(
    "/{location_id}/sync",
    response_model=SyncJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def sync_location(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """ "Sync location": its documents, their files, and its open conditions (manual for
    now)."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_write, location.operator_id, read_perm=Perm.bill_tos_read)
    if location.removed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PestPac no longer lists this location under its bill-to",
        )
    job = sync_jobs.enqueue_location(
        db, location, requested_by=scope.user_id, kind=SyncJobKind.location_sync
    )
    db.commit()
    return job
