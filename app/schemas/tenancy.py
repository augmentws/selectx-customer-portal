import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models import SyncJobKind, SyncJobStatus
from app.schemas.auth import PASSWORD_MIN_LENGTH
from app.schemas.pestpac import LocationSyncSummary
from app.security.permissions import RoleScope

Name = Field(min_length=1, max_length=200)


class PartialUpdate(BaseModel):
    """Only fields present in the request are changed. Fields in `_not_nullable` may be omitted
    but not sent as null."""

    _not_nullable: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _reject_explicit_nulls(self):
        nulls = [
            f for f in self._not_nullable if f in self.model_fields_set and getattr(self, f) is None
        ]
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self


class OperatorCreate(BaseModel):
    name: str = Name
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    pestpac_tenant_id: str = Field(min_length=1, max_length=64)


class OperatorUpdate(PartialUpdate):
    _not_nullable = ("name", "is_active", "pestpac_tenant_id")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    pestpac_tenant_id: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None


class OperatorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    pestpac_tenant_id: str
    is_active: bool
    created_at: datetime


class Crumb(BaseModel):
    """One step of a record's place in the hierarchy, for breadcrumbs."""

    kind: Literal["operator", "company", "bill_to", "location"]
    id: uuid.UUID
    name: str


class CompanyCreate(BaseModel):
    name: str = Name


class CompanyUpdate(PartialUpdate):
    _not_nullable = ("name", "is_active")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operator_id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime


class CompanyDetail(CompanyRead):
    # The company's parents, outermost first.
    trail: list[Crumb]


class BillToCreate(BaseModel):
    pestpac_bill_to_id: int = Field(gt=0)
    # Defaults to "{Company} · {Address}, {City}" from PestPac.
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class BillToUpdate(PartialUpdate):
    _not_nullable = ("name", "is_active")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class BillToRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operator_id: uuid.UUID
    company_id: uuid.UUID
    pestpac_bill_to_id: int
    name: str
    description: str | None
    is_active: bool
    onboarded_at: datetime
    onboarded_by: uuid.UUID | None
    pestpac_bill_to_code: str | None
    pestpac_company: str | None
    address: str | None
    address2: str | None
    city: str | None
    state: str | None
    zip: str | None
    phone: str | None
    pestpac_type: str | None
    pestpac_fetched_at: datetime | None
    # Locations PestPac currently lists under this bill-to.
    location_count: int = 0


class BillToDetail(BillToRead):
    trail: list[Crumb]


class BillToSynced(BillToRead):
    """A bill-to after onboarding or refresh, with what the location sync changed."""

    locations_sync: LocationSyncSummary


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bill_to_id: uuid.UUID
    pestpac_location_id: int
    pestpac_location_code: str | None
    pestpac_company: str | None
    address: str | None
    address2: str | None
    city: str | None
    state: str | None
    zip: str | None
    phone: str | None
    email: str | None
    pestpac_type: str | None
    account_type: str | None
    latitude: float | None
    longitude: float | None
    pestpac_active: bool
    removed_at: datetime | None
    pestpac_fetched_at: datetime
    # Orders PestPac still lists as open (not yet billed) for this location.
    open_order_count: int = 0
    # Of those, the ones already worked (awaiting billing).
    worked_order_count: int = 0
    # WorkDate of the latest worked order (PestPac wall-clock time).
    last_service_at: datetime | None = None


class LocationDetail(LocationRead):
    trail: list[Crumb]


class MemberCreate(BaseModel):
    email: EmailStr
    role: str
    # Required when the email has no account yet; the user must change it at first sign-in.
    temporary_password: str | None = Field(
        default=None, min_length=PASSWORD_MIN_LENGTH, max_length=256
    )


class MemberUpdate(BaseModel):
    role: str


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    tenant_id: uuid.UUID
    role: str
    must_change_password: bool
    created_at: datetime


class MemberCreated(MemberRead):
    user_created: bool


class CompanyMemberRead(BaseModel):
    """A customer's user, granted a company-scoped role on one company."""

    user_id: uuid.UUID
    email: EmailStr
    company_id: uuid.UUID
    role: str
    must_change_password: bool
    created_at: datetime


class CompanyMemberCreated(CompanyMemberRead):
    user_created: bool


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    description: str


class RoleRead(BaseModel):
    name: str
    description: str
    scope: RoleScope
    permissions: list[str]


class ServiceOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bill_to_id: uuid.UUID
    location_id: uuid.UUID | None
    pestpac_order_id: int
    pestpac_location_id: int
    order_number: str | None
    service_code: str | None
    description: str | None
    work_date: datetime | None
    tech_name: str | None
    tech_id: int | None
    technician_id: uuid.UUID | None
    # Resolved technician's name, or tech_name when the lookup hasn't succeeded yet.
    technician_name: str | None
    location_instructions: str | None
    service_instructions: str | None
    order_instructions: str | None
    technician_comment: str | None
    pestpac_invoice_id: int | None
    posted: bool
    posted_at: datetime | None
    closed_at: datetime | None
    pestpac_fetched_at: datetime
    last_event_at: datetime | None


class PostedServiceOrderRead(ServiceOrderRead):
    # The location's PestPac Company (its name), for lists spanning locations.
    location_name: str | None
    # The order's service report, if one was started (an order has at most one).
    report_id: uuid.UUID | None


class TechnicianOption(BaseModel):
    id: uuid.UUID
    name: str


class PostedServiceOrderPage(BaseModel):
    items: list[PostedServiceOrderRead]
    # Matching the filters; the choices below are over all the posted orders.
    total: int
    limit: int
    offset: int
    technicians: list[TechnicianOption]
    service_codes: list[str]


class SyncJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: SyncJobKind
    status: SyncJobStatus
    bill_to_id: uuid.UUID
    location_id: uuid.UUID | None
    progress: dict
    error: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pestpac_note_id: int
    note_date: datetime | None
    note_code: str | None
    note: str | None
    created_by_user: str | None
    # Technician's name when the author is a known technician, else created_by_user.
    created_by_name: str | None
    show_on_portal: bool
    location_id: uuid.UUID | None
    service_order_id: uuid.UUID | None
    pestpac_order_id: int | None
    pestpac_invoice_id: int | None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: str
    pestpac_document_id: int
    name: str | None
    file_name: str | None
    # PestPac local wall-clock time, as stored.
    document_date: datetime | None
    starting_effective_date: datetime | None
    ending_effective_date: datetime | None
    is_tech_photo: bool
    include_on: dict[str, bool]
    location_id: uuid.UUID | None
    service_order_id: uuid.UUID | None
    pestpac_order_id: int | None
    has_file: bool
    content_type: str | None
    size_bytes: int | None
    # Why the file isn't stored yet, if a download was tried.
    file_error: str | None
    # PestPac can't provide the file (e.g. over its API's 10 MB limit): not tried again.
    file_unavailable: bool


class ConditionInspectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service_order_id: uuid.UUID | None
    pestpac_order_id: int | None
    # PestPac local wall-clock time, as stored.
    detail_date: datetime | None
    username: str | None
    status: str | None
    comment: str | None


class ConditionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pestpac_issue_id: int
    location_id: uuid.UUID | None
    service_order_id: uuid.UUID | None
    pestpac_order_id: int | None
    area: str | None
    specific_area: str | None
    area_hierarchy: str | None
    condition_type: str | None
    condition: str | None
    action: str | None
    detail: str | None
    status: str | None
    severity: str | None
    responsibility: str | None
    category: str | None
    opened_by_user: str | None
    # PestPac local wall-clock times, as stored.
    date_opened: datetime | None
    date_closed: datetime | None
    last_inspected_date: datetime | None
    inspections: list[ConditionInspectionRead]


class ConditionRead(ConditionBase):
    documents: list[DocumentRead]


class ServiceOrderDetail(PostedServiceOrderRead):
    """One order for its own page: where it sits, and its stored invoice (if billed)."""

    trail: list[Crumb]
    # Our invoice record for it; reading the invoice still needs billing:read.
    invoice_id: uuid.UUID | None


# How an item relates to an order: PestPac links it to the order ("order"; for conditions,
# "opened" on it or "inspected" on it), or it's the location's and dated within a day of the
# order's work date ("same_day"), since PestPac rarely links them.
OrderLink = Literal["order", "same_day"]


class OrderDocument(DocumentRead):
    link: OrderLink


class OrderCondition(ConditionRead):
    link: Literal["opened", "inspected", "same_day"]


class OrderNote(NoteRead):
    link: OrderLink


class ServiceOrderRelated(BaseModel):
    """What was logged around an order: linked items first, then same-day ones."""

    documents: list[OrderDocument]
    conditions: list[OrderCondition]
    notes: list[OrderNote]
