import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Company, Location
from app.schemas.inspections import RiskInspectionDetail, RiskInspectionListItem
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import risk_inspections

router = APIRouter(tags=["risk-inspections"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("/companies/{company_id}/risk-inspections", response_model=list[RiskInspectionListItem])
def list_company_risk_inspections(
    company_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Risk inspections of every location under the company's bill-tos, newest first."""
    company = db.get(Company, company_id)
    if company is None:
        raise _not_found()
    scope.require(Perm.bill_tos_read, company.operator_id, read_perm=Perm.companies_read)
    return [
        risk_inspections.list_item(s) for s in risk_inspections.list_for_company(db, company.id)
    ]


@router.get(
    "/locations/{location_id}/risk-inspections", response_model=list[RiskInspectionListItem]
)
def list_location_risk_inspections(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The location's risk inspections, newest first."""
    location = db.get(Location, location_id)
    if location is None:
        raise _not_found()
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return [
        risk_inspections.list_item(s) for s in risk_inspections.list_for_location(db, location.id)
    ]


@router.get("/risk-inspections/{inspection_id}", response_model=RiskInspectionDetail)
def get_risk_inspection(
    inspection_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """One risk inspection with its zones, notes, photos (as stored file ids), and materials:
    what the RiskGate PDF report shows."""
    submission = risk_inspections.get(db, inspection_id)
    if submission is None:
        raise _not_found()
    scope.require(Perm.bill_tos_read, submission.operator_id, read_perm=Perm.bill_tos_read)
    return risk_inspections.detail(db, submission)
