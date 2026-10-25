import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1._pestpac_errors import pestpac_errors
from app.api.v1.bill_tos import bill_to_reads, bill_to_synced, posted_order_page
from app.db.session import get_db
from app.models import Company
from app.schemas.pestpac import BillToLookup
from app.schemas.tenancy import (
    BillToCreate,
    BillToRead,
    BillToSynced,
    CompanyDetail,
    CompanyRead,
    CompanyUpdate,
    PostedServiceOrderPage,
)
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import service_orders, tenancy, trail

router = APIRouter(prefix="/companies", tags=["companies"])


def _company_or_404(db: Session, company_id: uuid.UUID) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return company


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(
    company_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    company = _company_or_404(db, company_id)
    scope.require(Perm.companies_read, company.operator_id, read_perm=Perm.companies_read)
    return CompanyDetail.model_validate(
        {
            **CompanyRead.model_validate(company).model_dump(),
            "trail": trail.trail(db, operator_id=company.operator_id),
        }
    )


@router.patch("/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: uuid.UUID,
    data: CompanyUpdate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    company = _company_or_404(db, company_id)
    scope.require(Perm.companies_write, company.operator_id, read_perm=Perm.companies_read)
    return tenancy.update_company(db, company, data)


@router.get("/{company_id}/bill-tos", response_model=list[BillToRead])
def list_bill_tos(
    company_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    company = _company_or_404(db, company_id)
    scope.require(Perm.bill_tos_read, company.operator_id, read_perm=Perm.companies_read)
    return bill_to_reads(db, tenancy.list_bill_tos(db, company.id))


@router.get("/{company_id}/posted-service-orders", response_model=PostedServiceOrderPage)
def list_posted_service_orders(
    company_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Worked orders (billed or not) across all the company's bill-tos, oldest first."""
    company = _company_or_404(db, company_id)
    scope.require(Perm.bill_tos_read, company.operator_id, read_perm=Perm.companies_read)
    rows, total = service_orders.list_posted_orders(
        db, company_id=company.id, limit=limit, offset=offset
    )
    return posted_order_page(db, rows, total, limit, offset)


@router.post(
    "/{company_id}/bill-tos", response_model=BillToSynced, status_code=status.HTTP_201_CREATED
)
def onboard_bill_to(
    company_id: uuid.UUID,
    data: BillToCreate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    company = _company_or_404(db, company_id)
    scope.require(Perm.bill_tos_write, company.operator_id, read_perm=Perm.companies_read)
    with pestpac_errors():
        bill_to, summary = tenancy.onboard_bill_to(db, company, data, onboarded_by=scope.user_id)
    return bill_to_synced(db, bill_to, summary)


@router.get("/{company_id}/bill-tos/lookup", response_model=BillToLookup)
def lookup_bill_to(
    company_id: uuid.UUID,
    pestpac_bill_to_id: int = Query(gt=0),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Preview a PestPac bill-to before onboarding it. Nothing is stored."""
    company = _company_or_404(db, company_id)
    scope.require(Perm.bill_tos_write, company.operator_id, read_perm=Perm.companies_read)
    with pestpac_errors():
        return tenancy.lookup_bill_to(db, company, pestpac_bill_to_id)
