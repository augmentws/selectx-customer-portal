import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.tenancy import Crumb, PartialUpdate

# Templates embed images and fonts as data: URIs, so allow room for them.
MAX_TEMPLATE_CHARS = 2_000_000
MAX_PROMPT_CHARS = 50_000

TemplateHtml = Field(min_length=1, max_length=MAX_TEMPLATE_CHARS)

# --- Template fields --------------------------------------------------------------------------
# A template declares the fields its reports edit; the HTML reads them as `fields.<key>`. Values:
#   text        a string
#   paragraphs  a list of strings, one per paragraph
#   list        a list of strings (bullets)
#   sections    a list of {heading, paragraphs}
# Text may use **bold**; templates render it with the `rich` filter.

FieldType = Literal["text", "paragraphs", "list", "sections"]


class TemplateField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,49}$")
    label: str = Field(min_length=1, max_length=200)
    type: FieldType
    # Drafted by the LLM from the service order's notes (the rest are typed or defaulted).
    llm: bool = False
    # What the field is for: shown under it in the editor and given to the LLM.
    help: str | None = Field(default=None, max_length=1000)
    # Starting value: a string for text, a list of strings for paragraphs and list.
    default: str | list[str] | None = None


def _unique_keys(fields: list[TemplateField]) -> list[TemplateField]:
    keys = [f.key for f in fields]
    if len(keys) != len(set(keys)):
        raise ValueError("field keys must be unique")
    return fields


TemplateFields = Annotated[list[TemplateField], Field(max_length=50), AfterValidator(_unique_keys)]


class ReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(max_length=300)
    paragraphs: list[str] = Field(max_length=50)


class ReportTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    html: str = TemplateHtml
    fields: TemplateFields = []
    prompt: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    llm_model: str | None = Field(default=None, max_length=200)


class ReportTemplateUpdate(PartialUpdate):
    _not_nullable = ("name", "html", "is_active")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    html: str | None = Field(default=None, min_length=1, max_length=MAX_TEMPLATE_CHARS)
    fields: TemplateFields | None = None
    prompt: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    llm_model: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None


class ReportTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operator_id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None
    html: str
    fields: list[TemplateField]
    prompt: str | None
    llm_model: str | None
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ReportPreview(BaseModel):
    """Unsaved template HTML, rendered against a real location; `fields` get sample values
    (and the sample order, conditions, and photos stand in) so every part can be checked."""

    html: str = TemplateHtml
    fields: TemplateFields = []


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


class ReportServiceOrder(BaseModel):
    pestpac_order_id: int
    order_number: str | None
    # PestPac local wall-clock time.
    work_date: datetime | None
    service_code: str | None
    description: str | None
    technician_name: str | None
    # This order's place among the location's worked orders by work date (1 = first).
    service_number: int | None


class ReportCondition(BaseModel):
    pestpac_issue_id: int
    area: str | None
    area_hierarchy: str | None
    condition: str | None
    category: str | None
    severity: str | None
    responsibility: str | None
    status: str | None
    date_opened: datetime | None
    action: str | None


class ReportPhoto(BaseModel):
    src: str = Field(description="A data: URI (downscaled), ready for <img src>")
    caption: str | None


class ReportContext(BaseModel):
    """Top-level template variables: {{ location.city }}, {{ generated_at }}, ...

    Reports started from a service order also fill `service_order`, `conditions`, `fields`,
    and `photos`; a location's one-click PDF leaves them empty, so templates check them."""

    operator: ReportOperator
    company: ReportCompany
    bill_to: ReportBillTo
    location: ReportLocation
    # In UTC; format in the template, e.g. {{ generated_at.strftime('%B %-d, %Y') }}.
    generated_at: datetime
    # Parsed from the location name ("CHIPOTLE - STORE #2254" -> "2254").
    store_number: str | None = None
    service_order: ReportServiceOrder | None = None
    # The location's open conditions when the report was started.
    conditions: list[ReportCondition] = []
    # The template's fields: text is a string; paragraphs and list are lists of strings;
    # sections are lists of {heading, paragraphs}.
    fields: dict[str, Any] = {}
    # Selected photos, in order.
    photos: list[ReportPhoto] = []
    revision: int | None = None


# --- Reports (one per service order, editable until final) ------------------------------------


class ReportNoteItem(BaseModel):
    """A note dated near the order's work date, as the LLM sees it if selected."""

    note_id: uuid.UUID
    pestpac_note_id: int
    note_date: datetime | None
    note_code: str | None
    author: str | None
    text: str | None
    linked_to_order: bool
    selected: bool


class ReportTechnicianComment(BaseModel):
    """The order's TechnicianComment, taken when the report was started. Sent to the LLM with
    the notes when selected."""

    text: str
    author: str | None
    selected: bool


class ReportPhotoItem(BaseModel):
    """An image dated near the order's work date. Selected ones appear in the report, in
    list order, with their caption."""

    document_id: uuid.UUID
    pestpac_document_id: int
    name: str | None
    file_name: str | None
    document_date: datetime | None
    selected: bool
    caption: str | None = Field(default=None, max_length=300)


class ReportData(BaseModel):
    """What goes into the PDF (and the narrative draft), stored apart from the PDF itself."""

    # A snapshot taken when the report was started: ReportContext minus fields and photos.
    context: dict[str, Any]
    fields: dict[str, Any]
    notes: list[ReportNoteItem]
    photos: list[ReportPhotoItem]
    # None when the order had no comment (and for reports started before this existed).
    technician_comment: ReportTechnicianComment | None = None


class ReportCreate(BaseModel):
    template_id: uuid.UUID
    service_order_id: uuid.UUID


class ReportNoteChoice(BaseModel):
    note_id: uuid.UUID
    selected: bool


class ReportPhotoChoice(BaseModel):
    document_id: uuid.UUID
    selected: bool
    caption: str | None = Field(default=None, max_length=300)


class ReportUpdate(BaseModel):
    """Edits to a draft. `photos` lists every candidate photo in the order wanted."""

    fields: dict[str, Any] | None = None
    notes: list[ReportNoteChoice] | None = Field(default=None, max_length=1000)
    technician_comment_selected: bool | None = None
    photos: list[ReportPhotoChoice] | None = Field(default=None, max_length=1000)


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operator_id: uuid.UUID
    company_id: uuid.UUID
    location_id: uuid.UUID
    service_order_id: uuid.UUID
    template_id: uuid.UUID
    template_name: str
    template_version: int
    # The template's fields, for the editor.
    template_fields: list[TemplateField]
    revision: int
    revises_id: uuid.UUID | None
    # The order's newest version (this one, or a later revision).
    latest_id: uuid.UUID
    # Operator, company, bill-to, and location, for breadcrumbs.
    trail: list[Crumb]
    status: str
    data: ReportData
    draft_requested_at: datetime | None
    drafted_at: datetime | None
    draft_error: str | None
    draft_usage: dict[str, Any] | None
    has_pdf: bool
    pdf_size_bytes: int | None
    finalized_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReportSummary(BaseModel):
    """A report in a location's list (no data)."""

    id: uuid.UUID
    service_order_id: uuid.UUID
    order_number: str | None
    work_date: datetime | None
    template_id: uuid.UUID
    template_name: str
    revision: int
    status: str
    has_pdf: bool
    finalized_at: datetime | None
    updated_at: datetime
