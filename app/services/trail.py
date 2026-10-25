"""Breadcrumb trails: a record's parents, outermost first."""

import uuid

from sqlalchemy.orm import Session

from app.models import BillTo, Company, Location, Tenant
from app.schemas.tenancy import Crumb


def location_name(location: Location) -> str:
    return location.pestpac_company or f"LocationID {location.pestpac_location_id}"


def trail(
    db: Session,
    *,
    operator_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
    bill_to_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
) -> list[Crumb]:
    """Crumbs for the given ids, in hierarchy order. Callers pass only the levels above the
    page they're building (plus the location, for pages beneath one)."""
    crumbs = [Crumb(kind="operator", id=operator_id, name=db.get(Tenant, operator_id).name)]
    if company_id is not None:
        crumbs.append(Crumb(kind="company", id=company_id, name=db.get(Company, company_id).name))
    if bill_to_id is not None:
        crumbs.append(Crumb(kind="bill_to", id=bill_to_id, name=db.get(BillTo, bill_to_id).name))
    if location_id is not None:
        location = db.get(Location, location_id)
        crumbs.append(Crumb(kind="location", id=location_id, name=location_name(location)))
    return crumbs
