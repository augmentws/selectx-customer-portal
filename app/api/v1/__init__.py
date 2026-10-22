from fastapi import APIRouter

from app.api.v1 import (
    auth,
    bill_tos,
    companies,
    locations,
    members,
    operators,
    pestpac_connection,
    reports,
    roles,
    service_orders,
    sync_jobs,
    webhooks,
)

router = APIRouter(prefix="/v1")
router.include_router(auth.router)
router.include_router(operators.router)
router.include_router(companies.router)
router.include_router(bill_tos.router)
router.include_router(locations.router)
router.include_router(service_orders.router)
router.include_router(sync_jobs.router)
router.include_router(members.router)
router.include_router(pestpac_connection.router)
router.include_router(reports.router)
router.include_router(roles.router)
router.include_router(webhooks.router)
