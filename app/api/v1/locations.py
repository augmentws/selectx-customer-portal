import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1._pestpac_errors import require_sync_active
from app.api.v1.bill_tos import PostedOrderFilters, posted_order_page
from app.db.session import get_db
from app.models import BillTo, Location, SyncJobKind
from app.schemas.tenancy import (
    ConditionBase,
    ConditionRead,
    DocumentRead,
    LocationAreaRead,
    LocationDetail,
    NoteRead,
    PostedServiceOrderPage,
    ServiceOrderRead,
    SyncJobRead,
)
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import (
    conditions,
    documents,
    location_areas,
    notes,
    service_orders,
    sync_jobs,
    trail,
)

router = APIRouter(prefix="/locations", tags=["locations"])


def _location_or_404(db: Session, location_id: uuid.UUID) -> Location:
    location = db.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return location


@router.get("/{location_id}", response_model=LocationDetail)
def get_location(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    stats = service_orders.location_order_stats(db, [location.id])
    bill_to = db.get(BillTo, location.bill_to_id)
    return LocationDetail.model_validate(
        {
            **service_orders.location_read(location, stats).model_dump(),
            "trail": trail.trail(
                db,
                operator_id=location.operator_id,
                company_id=bill_to.company_id,
                bill_to_id=bill_to.id,
            ),
        }
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


@router.get("/{location_id}/areas", response_model=list[LocationAreaRead])
def list_areas(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The location's areas as PestPac defines them, in tree order, with each area's open
    conditions. Filled by "Sync location"; empty when none are set up in PestPac."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return [
        LocationAreaRead.model_validate(
            {
                **{
                    f: getattr(area, f)
                    for f in LocationAreaRead.model_fields
                    if f != "open_conditions"
                },
                "open_conditions": count,
            }
        )
        for area, count in location_areas.list_for_location(db, location.id)
    ]


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


@router.get("/{location_id}/posted-service-orders", response_model=PostedServiceOrderPage)
def list_posted_service_orders(
    location_id: uuid.UUID,
    filters: PostedOrderFilters = Depends(),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """The location's worked orders without a stored invoice, filtered and sorted as a
    bill-to's."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return posted_order_page(db, filters, location_id=location.id)


@router.get("/{location_id}/invoiced-service-orders", response_model=PostedServiceOrderPage)
def list_invoiced_service_orders(
    location_id: uuid.UUID,
    filters: PostedOrderFilters = Depends(),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """The location's orders that have a stored invoice (the orders only, not the invoices),
    filtered and sorted as its posted orders. Needs billing:read, like invoices."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.billing_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return posted_order_page(db, filters, location_id=location.id, state="invoiced")


@router.get("/{location_id}/open-service-orders", response_model=PostedServiceOrderPage)
def list_open_service_orders(
    location_id: uuid.UUID,
    filters: PostedOrderFilters = Depends(),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """The location's orders not worked yet (PestPac still lists them), filtered and sorted as
    its posted orders."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return posted_order_page(db, filters, location_id=location.id, state="open")


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
    require_sync_active()
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
    require_sync_active()
    job = sync_jobs.enqueue_location(
        db, location, requested_by=scope.user_id, kind=SyncJobKind.location_sync
    )
    db.commit()
    return job
