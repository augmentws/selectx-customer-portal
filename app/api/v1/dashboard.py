import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import BillTo, Company
from app.schemas.dashboard import CompanyDashboard
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/companies/{company_id}/dashboard", response_model=CompanyDashboard)
def get_company_dashboard(
    company_id: uuid.UUID,
    bill_to_id: uuid.UUID | None = Query(default=None, description="Limit to one bill-to"),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(Perm.dashboards_read, company.operator_id, read_perm=Perm.companies_read)
    if bill_to_id is not None:
        bill_to = db.get(BillTo, bill_to_id)
        if bill_to is None or bill_to.company_id != company.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return dashboard.company_dashboard(db, company.id, bill_to_id)
