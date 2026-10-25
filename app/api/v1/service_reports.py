import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Location, Report, ReportTemplate, ServiceOrder
from app.schemas.reports import ReportCreate, ReportRead, ReportSummary, ReportUpdate
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import reports, service_reports
from app.services.reports import TemplateRenderError
from app.services.service_reports import ReportInputError, ReportStateError
from app.storage import StorageError, StorageNotConfiguredError, get_storage

router = APIRouter(tags=["reports"])

PDF_RESPONSE = {200: {"content": {"application/pdf": {}}, "description": "The report as PDF"}}
HTML_RESPONSE = {200: {"content": {"text/html": {}}, "description": "The report as HTML"}}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _report_or_404(db: Session, report_id: uuid.UUID) -> Report:
    report = db.get(Report, report_id)
    if report is None:
        raise _not_found()
    return report


def _read(db: Session, report: Report) -> ReportRead:
    template = db.get(ReportTemplate, report.template_id)
    return ReportRead.model_validate(
        {
            **{f: getattr(report, f) for f in ReportRead.model_fields if hasattr(report, f)},
            "template_name": template.name,
            "template_fields": reports.template_fields(template),
            "data": service_reports.report_data(report),
            "has_pdf": report.pdf_storage_key is not None,
            "latest_id": service_reports.report_ids_for_orders(db, [report.service_order_id])[
                report.service_order_id
            ],
        }
    )


def _errors(exc: Exception) -> HTTPException:
    if isinstance(exc, ReportStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, StorageNotConfiguredError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, StorageError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    # ReportInputError, TemplateRenderError
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/locations/{location_id}/service-reports", response_model=list[ReportSummary])
def list_service_reports(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    location = db.get(Location, location_id)
    if location is None:
        raise _not_found()
    scope.require(Perm.reports_read, location.operator_id, read_perm=Perm.bill_tos_read)
    rows = service_reports.list_reports(db, location_id=location.id)
    summaries = []
    for r in rows:
        order = db.get(ServiceOrder, r.service_order_id)
        template = db.get(ReportTemplate, r.template_id)
        summaries.append(
            ReportSummary(
                id=r.id,
                service_order_id=r.service_order_id,
                order_number=order.order_number,
                work_date=order.work_date,
                template_id=r.template_id,
                template_name=template.name,
                revision=r.revision,
                status=r.status,
                has_pdf=r.pdf_storage_key is not None,
                finalized_at=r.finalized_at,
                updated_at=r.updated_at,
            )
        )
    return summaries


@router.post(
    "/locations/{location_id}/service-reports",
    response_model=ReportRead,
    status_code=status.HTTP_201_CREATED,
)
def create_service_report(
    location_id: uuid.UUID,
    data: ReportCreate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Start a report for one of the location's service orders, with its notes and photos
    dated near the work date offered for selection."""
    location = db.get(Location, location_id)
    if location is None:
        raise _not_found()
    scope.require(Perm.reports_write, location.operator_id, read_perm=Perm.bill_tos_read)
    order = db.get(ServiceOrder, data.service_order_id)
    template = db.get(ReportTemplate, data.template_id)
    if order is None or order.location_id != location.id:
        raise _not_found()
    if (
        template is None
        or not template.is_active
        or template.company_id != reports.location_company_id(db, location)
    ):
        raise _not_found()
    try:
        report = service_reports.create_report(db, template, order, scope.user_id)
    except service_reports.ReportExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This service order already has a report; open it or revise it instead.",
        ) from exc
    return _read(db, report)


@router.get("/service-reports/{report_id}", response_model=ReportRead)
def get_service_report(
    report_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    report = _report_or_404(db, report_id)
    scope.require(Perm.reports_read, report.operator_id, read_perm=Perm.bill_tos_read)
    return _read(db, report)


@router.patch("/service-reports/{report_id}", response_model=ReportRead)
def update_service_report(
    report_id: uuid.UUID,
    data: ReportUpdate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Edit a draft: field values, which notes the narrative is drafted from, and which photos
    appear (in order, with captions)."""
    report = _report_or_404(db, report_id)
    scope.require(Perm.reports_write, report.operator_id, read_perm=Perm.bill_tos_read)
    template = db.get(ReportTemplate, report.template_id)
    try:
        report = service_reports.update_report(db, report, template, data, scope.user_id)
    except (ReportInputError, ReportStateError) as exc:
        raise _errors(exc) from None
    return _read(db, report)


@router.post(
    "/service-reports/{report_id}/draft",
    response_model=ReportRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def draft_service_report(
    report_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Queue the narrative draft: the selected notes go to the LLM with the template's prompt;
    the reply fills the template's LLM fields. Runs in the worker; poll the report."""
    report = _report_or_404(db, report_id)
    scope.require(Perm.reports_write, report.operator_id, read_perm=Perm.bill_tos_read)
    try:
        report = service_reports.request_draft(db, report, scope.user_id)
    except (ReportInputError, ReportStateError) as exc:
        raise _errors(exc) from None
    return _read(db, report)


@router.get(
    "/service-reports/{report_id}/preview",
    response_class=Response,
    responses=HTML_RESPONSE,
)
def preview_service_report(
    report_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The report as HTML, rendered from its saved data exactly as the PDF will be."""
    report = _report_or_404(db, report_id)
    scope.require(Perm.reports_read, report.operator_id, read_perm=Perm.bill_tos_read)
    try:
        storage = _storage_or_none()
        html = service_reports.render_report_html(db, report, storage)
    except (ReportInputError, TemplateRenderError, StorageError) as exc:
        raise _errors(exc) from None
    return Response(
        html,
        media_type="text/html",
        # Shown in a sandboxed iframe; never run as a page of ours.
        headers={
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def _storage_or_none():
    try:
        return get_storage()
    except StorageNotConfiguredError:
        return None


@router.post("/service-reports/{report_id}/finalize", response_model=ReportRead)
def finalize_service_report(
    report_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Render the PDF from the saved data, store it, and lock the report."""
    report = _report_or_404(db, report_id)
    scope.require(Perm.reports_write, report.operator_id, read_perm=Perm.bill_tos_read)
    try:
        report = service_reports.finalize(db, report, get_storage(), scope.user_id)
    except (ReportInputError, ReportStateError, TemplateRenderError, StorageError) as exc:
        db.rollback()
        raise _errors(exc) from None
    return _read(db, report)


@router.post(
    "/service-reports/{report_id}/revise",
    response_model=ReportRead,
    status_code=status.HTTP_201_CREATED,
)
def revise_service_report(
    report_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Start a new draft revision from a final report's data."""
    report = _report_or_404(db, report_id)
    scope.require(Perm.reports_write, report.operator_id, read_perm=Perm.bill_tos_read)
    try:
        return _read(db, service_reports.revise(db, report, scope.user_id))
    except ReportStateError as exc:
        raise _errors(exc) from None


@router.get(
    "/service-reports/{report_id}/pdf",
    response_class=Response,
    responses=PDF_RESPONSE,
)
def get_service_report_pdf(
    report_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The stored PDF of a final report."""
    report = _report_or_404(db, report_id)
    scope.require(Perm.reports_read, report.operator_id, read_perm=Perm.bill_tos_read)
    if report.pdf_storage_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No PDF yet")
    try:
        stored = get_storage().get(report.pdf_storage_key)
    except StorageError as exc:
        raise _errors(exc) from None
    template = db.get(ReportTemplate, report.template_id)
    order = db.get(ServiceOrder, report.service_order_id)
    name = f"{template.name}-{order.order_number or order.pestpac_order_id}-r{report.revision}"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "report"
    return Response(
        stored.data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{safe}.pdf"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-cache",
        },
    )
