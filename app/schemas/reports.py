import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.tenancy import PartialUpdate

# Templates embed images and fonts as data: URIs, so allow room for them.
MAX_TEMPLATE_CHARS = 2_000_000

TemplateHtml = Field(min_length=1, max_length=MAX_TEMPLATE_CHARS)


class ReportTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    html: str = TemplateHtml


class ReportTemplateUpdate(PartialUpdate):
    _not_nullable = ("name", "html", "is_active")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    html: str | None = Field(default=None, min_length=1, max_length=MAX_TEMPLATE_CHARS)
    is_active: bool | None = None


class ReportTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operator_id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None
    html: str
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ReportPreview(BaseModel):
    """Unsaved template HTML, rendered against a real location."""

    html: str = TemplateHtml


# --- What templates can see -----------------------------------------------------------------
# The whitelist of fields a template receives. Add fields here (and to `build_context` in
# app/services/reports.py) to make them available; nothing else reaches a template.


class ReportOperator(BaseModel):
    name: str


class ReportCompany(BaseModel):
    name: str


class ReportBillTo(BaseModel):
    pestpac_bill_to_id: int
    name: str
    description: str | None
    pestpac_bill_to_code: str | None
    pestpac_company: str | None
    address: str | None
    address2: str | None
    city: str | None
    state: str | None
    zip: str | None
    phone: str | None


class ReportLocation(BaseModel):
    pestpac_location_id: int
    pestpac_location_code: str | None
    name: str | None = Field(description="PestPac's Company field for the location")
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


class ReportContext(BaseModel):
    """Top-level template variables: {{ location.city }}, {{ generated_at }}, ..."""

    operator: ReportOperator
    company: ReportCompany
    bill_to: ReportBillTo
    location: ReportLocation
    # In UTC; format in the template, e.g. {{ generated_at.strftime('%B %-d, %Y') }}.
    generated_at: datetime
