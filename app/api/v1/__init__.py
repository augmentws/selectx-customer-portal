from fastapi import APIRouter

from app.api.v1 import auth, items

router = APIRouter(prefix="/v1")
router.include_router(auth.router)
router.include_router(items.router)
