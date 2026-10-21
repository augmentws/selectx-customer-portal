import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Company
from app.schemas.tenancy import BillToCreate, BillToRead, CompanyRead, CompanyUpdate
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import pestpac_connection, tenancy

router = APIRouter(prefix="/companies", tags=["companies"])


def _company_or_404(db: Session, company_id: uuid.UUID) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return company


@router.get("/{company_id}", response_model=CompanyRead)
def get_company(
    company_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    company = _company_or_404(db, company_id)
    scope.require(Perm.companies_read, company.operator_id, read_perm=Perm.companies_read)
    return company


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
    return tenancy.list_bill_tos(db, company.id)


@router.post(
    "/{company_id}/bill-tos", response_model=BillToRead, status_code=status.HTTP_201_CREATED
)
def onboard_bill_to(
    company_id: uuid.UUID,
    data: BillToCreate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    company = _company_or_404(db, company_id)
    scope.require(Perm.bill_tos_write, company.operator_id, read_perm=Perm.companies_read)
    try:
        return tenancy.onboard_bill_to(db, company, data, onboarded_by=scope.user_id)
    except (tenancy.ConflictError, pestpac_connection.ConnectionNotReadyError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except tenancy.BillToNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None
    except pestpac_connection.PestPacUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
