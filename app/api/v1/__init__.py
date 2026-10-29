from fastapi import APIRouter

from app.api.v1 import (
    auth,
    bill_tos,
    companies,
    dashboard,
    documents,
    files,
    gocanvas_connection,
    invoices,
    locations,
    members,
    operators,
    pestpac_connection,
    reports,
    roles,
    search,
    service_orders,
    service_reports,
    sync_jobs,
    webhook_events,
    webhooks,
)

router = APIRouter(prefix="/v1")
router.include_router(auth.router)
router.include_router(operators.router)
router.include_router(companies.router)
router.include_router(dashboard.router)
router.include_router(bill_tos.router)
router.include_router(locations.router)
router.include_router(documents.router)
router.include_router(files.router)
router.include_router(invoices.router)
router.include_router(service_orders.router)
router.include_router(sync_jobs.router)
router.include_router(members.router)
router.include_router(members.company_router)
router.include_router(pestpac_connection.router)
router.include_router(gocanvas_connection.router)
router.include_router(reports.router)
router.include_router(service_reports.router)
router.include_router(roles.router)
router.include_router(search.router)
router.include_router(webhooks.router)
router.include_router(webhook_events.router)
