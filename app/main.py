from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.v1 import router as v1_router
from app.core.config import get_settings
from app.security.secrets import validate_keys


def _operation_id(route: APIRoute) -> str:
    # e.g. operators-list_operators -> Orval generates `useOperatorsListOperators`
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}-{route.name}"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_keys()  # a bad APP_ENCRYPTION_KEYS should stop startup, not the first save
    yield


app = FastAPI(
    title="Customer Portal API",
    version="0.1.0",
    generate_unique_id_function=_operation_id,
    lifespan=lifespan,
)

# The browser talks to the Next.js BFF; this only matters for direct dev tooling.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(v1_router)
