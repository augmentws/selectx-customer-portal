import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Company, Location, ReportTemplate
from app.schemas.reports import (
    ReportPreview,
    ReportTemplateCreate,
    ReportTemplateRead,
    ReportTemplateUpdate,
)
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import reports
from app.services.reports import TemplateRenderError

router = APIRouter(tags=["reports"])

PDF_RESPONSE = {200: {"content": {"application/pdf": {}}, "description": "The report as PDF"}}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _unprocessable(exc: TemplateRenderError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Template error: {exc}"
    )


def _pdf(content: bytes, filename: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or "report"
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}.pdf"',
            "Cache-Control": "no-store",
        },
    )


def _template_or_404(db: Session, template_id: uuid.UUID) -> ReportTemplate:
    template = db.get(ReportTemplate, template_id)
    if template is None:
        raise _not_found()
    return template


@router.get("/companies/{company_id}/report-templates", response_model=list[ReportTemplateRead])
def list_report_templates(
    company_id: uuid.UUID,
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    company = db.get(Company, company_id)
    if company is None:
        raise _not_found()
    scope.require(Perm.reports_read, company.operator_id, read_perm=Perm.companies_read)
    return reports.list_templates(db, company.id, include_inactive=include_inactive)


@router.post(
    "/companies/{company_id}/report-templates",
    response_model=ReportTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
def create_report_template(
    company_id: uuid.UUID,
    data: ReportTemplateCreate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    company = db.get(Company, company_id)
    if company is None:
        raise _not_found()
    scope.require(Perm.report_templates_write, company.operator_id, read_perm=Perm.companies_read)
    try:
        return reports.create_template(db, company, data, scope.user_id)
    except TemplateRenderError as exc:
        raise _unprocessable(exc) from None


@router.get("/report-templates/{template_id}", response_model=ReportTemplateRead)
def get_report_template(
    template_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    template = _template_or_404(db, template_id)
    scope.require(Perm.reports_read, template.operator_id, read_perm=Perm.companies_read)
    return template


@router.patch("/report-templates/{template_id}", response_model=ReportTemplateRead)
def update_report_template(
    template_id: uuid.UUID,
    data: ReportTemplateUpdate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    template = _template_or_404(db, template_id)
    scope.require(Perm.report_templates_write, template.operator_id, read_perm=Perm.companies_read)
    try:
        return reports.update_template(db, template, data, scope.user_id)
    except TemplateRenderError as exc:
        raise _unprocessable(exc) from None


def _location_or_404(db: Session, location_id: uuid.UUID) -> Location:
    location = db.get(Location, location_id)
    if location is None:
        raise _not_found()
    return location


@router.get(
    "/locations/{location_id}/reports/{template_id}",
    response_class=Response,
    responses=PDF_RESPONSE,
)
def generate_report(
    location_id: uuid.UUID,
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Render a template with the location's data and return the PDF."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.reports_read, location.operator_id, read_perm=Perm.bill_tos_read)
    template = db.get(ReportTemplate, template_id)
    # Only the location's own company's active templates.
    if (
        template is None
        or not template.is_active
        or template.company_id != reports.location_company_id(db, location)
    ):
        raise _not_found()
    try:
        content = reports.render_pdf(db, template.html, location)
    except TemplateRenderError as exc:
        raise _unprocessable(exc) from None
    return _pdf(content, f"{template.name}-{location.pestpac_location_id}")


@router.post(
    "/locations/{location_id}/report-preview",
    response_class=Response,
    responses=PDF_RESPONSE,
)
def preview_report(
    location_id: uuid.UUID,
    data: ReportPreview,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Render unsaved template HTML with a location's data, for template authors."""
    location = _location_or_404(db, location_id)
    scope.require(Perm.report_templates_write, location.operator_id, read_perm=Perm.bill_tos_read)
    try:
        content = reports.render_pdf(db, data.html, location)
    except TemplateRenderError as exc:
        raise _unprocessable(exc) from None
    return _pdf(content, f"preview-{location.pestpac_location_id}")
