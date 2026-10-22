import uuid
from datetime import datetime

from pydantic import BaseModel


class DashboardHeadline(BaseModel):
    locations: int  # currently listed under the scope's bill-tos
    locations_serviced: int  # with at least one worked order
    services: int  # worked (posted) orders, billed or not
    open_orders: int  # not yet worked and still listed by PestPac
    awaiting_billing: int  # worked, still listed (not yet billed)
    billed: int  # worked and no longer listed by PestPac
    technicians: int  # distinct technicians on worked orders
    # PestPac local wall-clock time, as stored on the order.
    first_service: datetime | None
    last_service: datetime | None


class MonthCount(BaseModel):
    month: str  # YYYY-MM
    services: int


class ServiceCodeCount(BaseModel):
    service_code: str | None
    services: int


class TechnicianCount(BaseModel):
    technician_id: uuid.UUID | None
    name: str | None
    services: int


class StoreRow(BaseModel):
    location_id: uuid.UUID
    bill_to_id: uuid.UUID
    pestpac_location_id: int
    store_number: str | None  # parsed from the location name, e.g. "#436"
    name: str | None
    city: str | None
    state: str | None
    latitude: float | None
    longitude: float | None
    pestpac_active: bool
    services: int
    open_orders: int
    last_service: datetime | None


class CompanyDashboard(BaseModel):
    """Service activity for a company, or one of its bill-tos. Findings, programs, and risk
    metrics are not available yet (see docs/customer-dashboard-plan.md)."""

    company_id: uuid.UUID
    bill_to_id: uuid.UUID | None
    as_of: datetime
    headline: DashboardHeadline
    services_by_month: list[MonthCount]
    services_by_code: list[ServiceCodeCount]
    top_technicians: list[TechnicianCount]
    stores: list[StoreRow]
