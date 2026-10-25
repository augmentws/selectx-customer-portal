"""PDF reports from customer-specific HTML templates.

Templates are Jinja, rendered in a sandbox (no access to Python internals) with
StrictUndefined (a misspelled variable is an error, not a blank) and autoescaping. They see
only the whitelisted fields in `app.schemas.reports.ReportContext`, as plain dicts.

WeasyPrint converts the HTML to PDF. Its URL fetcher allows only data: URIs, so a template
can't make the server request anything: images, stylesheets, and fonts must be embedded.
"""

import re
import uuid
from datetime import UTC, datetime

import weasyprint
from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from markupsafe import Markup, escape
from sqlalchemy import select
from sqlalchemy.orm import Session
from weasyprint.urls import URLFetcher

from app.models import BillTo, Company, Location, ReportTemplate, Tenant
from app.schemas.reports import (
    ReportBillTo,
    ReportCompany,
    ReportCondition,
    ReportContext,
    ReportLocation,
    ReportOperator,
    ReportPhoto,
    ReportServiceOrder,
    ReportTemplateCreate,
    ReportTemplateUpdate,
    TemplateField,
)
from app.services.dashboard import store_number

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def rich(value: object) -> Markup:
    """Escape text, then turn **bold** into <strong>. The only markup field text may carry."""
    parts = _BOLD.split("" if value is None else str(value))
    # split() alternates plain text and the bold groups; each piece is escaped.
    return Markup("").join(
        escape(part) if n % 2 == 0 else Markup("<strong>{}</strong>").format(part)
        for n, part in enumerate(parts)
    )


_env = SandboxedEnvironment(autoescape=True, undefined=StrictUndefined)
_env.filters["rich"] = rich


class TemplateRenderError(ValueError):
    """The template doesn't compile or fails to render. The message is safe to show admins."""


def _describe(exc: TemplateError) -> str:
    line = getattr(exc, "lineno", None)
    return f"{type(exc).__name__}{f' on line {line}' if line else ''}: {exc.message or exc}"


def render_html(html: str, context: ReportContext) -> str:
    try:
        template = _env.from_string(html)
        return template.render(context.model_dump(mode="python"))
    except TemplateError as exc:
        raise TemplateRenderError(_describe(exc)) from exc
    except (ArithmeticError, AttributeError, LookupError, TypeError, ValueError) as exc:
        # Errors raised by template expressions themselves, e.g. {{ 1 / 0 }}.
        raise TemplateRenderError(f"{type(exc).__name__}: {exc}") from exc


def html_to_pdf(html: str) -> bytes:
    fetcher = URLFetcher(allowed_protocols={"data"}, allow_redirects=False)
    return weasyprint.HTML(string=html, url_fetcher=fetcher).write_pdf()


def sample_value(field: TemplateField):
    """A placeholder value of the field's type (its default when it has one)."""
    if field.default is not None:
        return field.default
    match field.type:
        case "text":
            return f"Sample {field.label.lower()}"
        case "paragraphs":
            return [f"Sample {field.label.lower()}, with **bold** text.", "A second paragraph."]
        case "list":
            return ["First item with **bold** text.", "Second item."]
        case "sections":
            return [
                {"heading": "Sample area", "paragraphs": ["Findings with **bold** text."]},
                {"heading": "Second area", "paragraphs": ["More findings."]},
            ]


# A small grey PNG, so templates can be checked against sample photos.
_SAMPLE_PHOTO = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mN89+5d"
    "PQAJCAN/1GDL5wAAAABJRU5ErkJggg=="
)


def sample_context(fields: list[TemplateField] | None = None) -> ReportContext:
    """Placeholder data with every field set, used to check a template when it's saved."""
    return ReportContext(
        operator=ReportOperator(name="Select Exterminating"),
        company=ReportCompany(name="Sample Company"),
        bill_to=ReportBillTo(
            pestpac_bill_to_id=100000,
            name="Sample Company · 1 Main St, New York",
            description="Sample bill-to",
            pestpac_bill_to_code="SAMPLE",
            pestpac_company="SAMPLE COMPANY",
            address="1 MAIN ST",
            address2=None,
            city="NEW YORK",
            state="NY",
            zip="10001",
            phone="212-555-0100",
        ),
        location=ReportLocation(
            pestpac_location_id=200000,
            pestpac_location_code="SAMPLE-1",
            name="SAMPLE COMPANY - STORE #1",
            address="1 MAIN ST",
            address2="FL 2",
            city="NEW YORK",
            state="NY",
            zip="10001",
            phone="212-555-0101",
            email="store1@example.com",
            pestpac_type="ENTERPRISE",
            account_type="Commercial",
            latitude=40.75,
            longitude=-73.99,
        ),
        generated_at=datetime.now(UTC),
        store_number="1",
        service_order=ReportServiceOrder(
            pestpac_order_id=300000,
            order_number="3000000",
            work_date=datetime(2026, 10, 5, 9, 30),
            service_code="RAMP MONITOR",
            description="QUALITY CONTROL INSPECTION",
            technician_name="Sample Technician",
            service_number=5,
        ),
        conditions=[
            ReportCondition(
                pestpac_issue_id=40000,
                area="Trash Room",
                area_hierarchy="Rear Entry -> Trash Room",
                condition="Structural opening",
                category="Structural",
                severity="Medium",
                responsibility="Customer",
                status="Open",
                date_opened=datetime(2026, 10, 5, 9, 45),
                action="Seal the opening.",
            )
        ],
        fields={f.key: sample_value(f) for f in fields or []},
        photos=[ReportPhoto(src=_SAMPLE_PHOTO, caption=f"Sample photo {n}") for n in (1, 2, 3)],
        revision=1,
    )


def check_template(html: str, fields: list[TemplateField] | None = None) -> None:
    """Raise TemplateRenderError unless the template renders against the sample data."""
    render_html(html, sample_context(fields))


def build_context(db: Session, location: Location) -> ReportContext:
    bill_to = db.get(BillTo, location.bill_to_id)
    company = db.get(Company, bill_to.company_id)
    operator = db.get(Tenant, location.operator_id)
    return ReportContext(
        operator=ReportOperator(name=operator.name),
        company=ReportCompany(name=company.name),
        bill_to=ReportBillTo.model_validate(bill_to, from_attributes=True),
        location=ReportLocation(
            name=location.pestpac_company,
            **{
                field: getattr(location, field)
                for field in ReportLocation.model_fields
                if field != "name"
            },
        ),
        generated_at=datetime.now(UTC),
        store_number=store_number(location.pestpac_company),
    )


def render_pdf(
    db: Session, html: str, location: Location, sample_fields: list[TemplateField] | None = None
) -> bytes:
    """The location's PDF. With `sample_fields` (template preview), the parts only a service
    report fills (order, conditions, fields, photos) use sample data."""
    context = build_context(db, location)
    if sample_fields is not None:
        sample = sample_context(sample_fields)
        context = context.model_copy(
            update={
                k: getattr(sample, k)
                for k in ("service_order", "conditions", "fields", "photos", "revision")
            }
        )
    return html_to_pdf(render_html(html, context))


def location_company_id(db: Session, location: Location) -> uuid.UUID:
    return db.scalar(select(BillTo.company_id).where(BillTo.id == location.bill_to_id))


def list_templates(
    db: Session, company_id: uuid.UUID, *, include_inactive: bool = False
) -> list[ReportTemplate]:
    query = select(ReportTemplate).where(ReportTemplate.company_id == company_id)
    if not include_inactive:
        query = query.where(ReportTemplate.is_active.is_(True))
    return list(db.scalars(query.order_by(ReportTemplate.name, ReportTemplate.id)))


VERSIONED = ("html", "fields", "prompt")


def template_fields(template: ReportTemplate) -> list[TemplateField]:
    return [TemplateField.model_validate(f) for f in template.fields or []]


def create_template(
    db: Session, company: Company, data: ReportTemplateCreate, user_id: uuid.UUID
) -> ReportTemplate:
    check_template(data.html, data.fields)
    template = ReportTemplate(
        operator_id=company.operator_id,
        company_id=company.id,
        name=data.name,
        description=data.description,
        html=data.html,
        fields=[f.model_dump() for f in data.fields],
        prompt=data.prompt,
        llm_model=data.llm_model,
        version=1,
        is_active=True,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(template)
    db.commit()
    return template


def update_template(
    db: Session, template: ReportTemplate, data: ReportTemplateUpdate, user_id: uuid.UUID
) -> ReportTemplate:
    changes = data.model_dump(exclude_unset=True)
    if "html" in changes or "fields" in changes:
        fields = data.fields if "fields" in changes else template_fields(template)
        check_template(changes.get("html", template.html), fields)
    # HTML, fields, and prompt work together; changing any is a new version.
    if any(changes.get(k, getattr(template, k)) != getattr(template, k) for k in VERSIONED):
        template.version += 1
    for field, value in changes.items():
        setattr(template, field, value)
    template.updated_by = user_id
    db.commit()
    return template
