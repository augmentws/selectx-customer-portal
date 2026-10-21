from fastapi import APIRouter

from app.api.v1 import auth, bill_tos, companies, members, operators, pestpac_connection, roles

router = APIRouter(prefix="/v1")
router.include_router(auth.router)
router.include_router(operators.router)
router.include_router(companies.router)
router.include_router(bill_tos.router)
router.include_router(members.router)
router.include_router(pestpac_connection.router)
router.include_router(roles.router)
