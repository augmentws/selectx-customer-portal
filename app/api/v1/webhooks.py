import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.services import gocanvas, webhooks
from app.services.webhooks import RequestClient

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookAck(BaseModel):
    status: str = "accepted"


def _client(request: Request) -> RequestClient:
    return RequestClient(
        ip=request.client.host if request.client else None,
        forwarded_for=request.headers.get("x-forwarded-for"),
        user_agent=request.headers.get("user-agent"),
    )


async def _body(request: Request) -> bytes:
    """The request body, refusing anything over WEBHOOK_MAX_BODY_BYTES (413), declared or not."""
    limit = get_settings().webhook_max_body_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Too large")
    # Read in chunks and stop at the limit: a chunked request declares no length, and reading
    # it whole first would let a public endpoint buffer any amount.
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Too large")
    return bytes(raw)


@router.post("/pestpac", response_model=WebhookAck)
async def receive_pestpac(request: Request, db: Session = Depends(get_db)):
    """PestPac webhook deliveries. Public (PestPac holds no session); authenticity comes from
    the HMAC signature. Answers the same whether the event was stored, dropped, or a
    redelivery, so callers can't probe which bill-tos are onboarded."""
    raw = await _body(request)
    try:
        # Sync database work; keep it off the event loop.
        await run_in_threadpool(
            webhooks.receive,
            db,
            raw,
            signatures=request.headers.getlist("signature"),
            timestamp=request.headers.get("timestamputc"),
            client=_client(request),
        )
    except webhooks.InvalidWebhookError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    return WebhookAck()


@router.post("/gocanvas/{operator_id}", response_model=WebhookAck)
async def receive_gocanvas(operator_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """GoCanvas webhook requests for one operator. Public; every request is stored as received
    (headers minus credentials, body, IP, user agent) until GoCanvas's format is known. Answers
    the same for unknown operators, so the URL can't be used to probe them."""
    raw = await _body(request)
    await run_in_threadpool(
        gocanvas.receive,
        db,
        operator_id,
        method=request.method,
        query_string=request.url.query,
        headers=list(request.headers.items()),
        raw=raw,
        client=_client(request),
    )
    return WebhookAck()


# GET and PUT are stored too (a verification ping, or a sender using PUT), but kept out of the
# OpenAPI document so the receiver has one operation.
router.add_api_route(
    "/gocanvas/{operator_id}",
    receive_gocanvas,
    methods=["GET", "PUT"],
    response_model=WebhookAck,
    include_in_schema=False,
)
