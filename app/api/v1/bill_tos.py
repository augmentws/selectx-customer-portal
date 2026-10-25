import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1._pestpac_errors import pestpac_errors
from app.db.session import get_db
from app.models import BillTo, ServiceOrder
from app.schemas.pestpac import LocationSyncSummary
from app.schemas.tenancy import (
    BillToRead,
    BillToSynced,
    BillToUpdate,
    LocationRead,
    PostedServiceOrderPage,
    PostedServiceOrderRead,
    ServiceOrderRead,
    SyncJobRead,
)
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import locations, service_orders, service_reports, sync_jobs, tenancy

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
    rows = locations.list_locations(db, bill_to.id)
    counts = service_orders.open_order_counts(db, [loc.id for loc in rows])
    return [
        LocationRead.model_validate(loc).model_copy(
            update={"open_order_count": counts.get(loc.id, 0)}
        )
        for loc in rows
    ]


@router.get("/{bill_to_id}/service-orders", response_model=list[ServiceOrderRead])
def list_service_orders(
    bill_to_id: uuid.UUID,
    status: Literal["open", "closed", "all"] = "open",
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Our copies of the bill-to's service orders; `closed` means billed (no longer in PestPac)."""
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_read, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    return service_orders.list_orders(db, bill_to_id=bill_to.id, status=status)


def posted_order_page(
    db: Session, rows: list[tuple[ServiceOrder, str | None]], total: int, limit: int, offset: int
) -> PostedServiceOrderPage:
    reports = service_reports.report_ids_for_orders(db, [order.id for order, _ in rows])
    items = [
        PostedServiceOrderRead.model_validate(
            ServiceOrderRead.model_validate(order).model_dump()
            | {"location_name": name, "report_id": reports.get(order.id)}
        )
        for order, name in rows
    ]
    return PostedServiceOrderPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{bill_to_id}/posted-service-orders", response_model=PostedServiceOrderPage)
def list_posted_service_orders(
    bill_to_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """The bill-to's worked orders (billed or not), oldest first."""
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_read, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    rows, total = service_orders.list_posted_orders(
        db, bill_to_id=bill_to.id, limit=limit, offset=offset
    )
    return posted_order_page(db, rows, total, limit, offset)


@router.post(
    "/{bill_to_id}/service-orders/sync",
    response_model=SyncJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def sync_service_orders(
    bill_to_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Queue a sync of every location's open orders. Returns the already-active job if one is
    queued or running for this bill-to."""
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_write, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    job = sync_jobs.enqueue_bill_to(db, bill_to, requested_by=scope.user_id)
    db.commit()
    return job


@router.post(
    "/{bill_to_id}/locations/sync",
    response_model=SyncJobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def sync_locations(
    bill_to_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """ "Sync location" for every location: documents, their files, and open conditions
    (manual for now). Returns the already-active job if one is queued or running."""
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_write, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    job = sync_jobs.enqueue_bill_to_location_sync(db, bill_to, requested_by=scope.user_id)
    db.commit()
    return job


@router.get("/{bill_to_id}/sync-jobs", response_model=list[SyncJobRead])
def list_sync_jobs(
    bill_to_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    bill_to = _bill_to_or_404(db, bill_to_id)
    scope.require(Perm.bill_tos_read, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    return sync_jobs.jobs_for_bill_to(db, bill_to.id)
