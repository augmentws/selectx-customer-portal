from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.services import webhooks

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookAck(BaseModel):
    status: str = "accepted"


@router.post("/pestpac", response_model=WebhookAck)
async def receive_pestpac(request: Request, db: Session = Depends(get_db)):
    """PestPac webhook deliveries. Public (PestPac holds no session); authenticity comes from
    the HMAC signature. Answers the same whether the event was stored, dropped, or a
    redelivery, so callers can't probe which bill-tos are onboarded."""
    limit = get_settings().webhook_max_body_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Too large")
    raw = await request.body()
    if len(raw) > limit:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Too large")
    try:
        # Sync database work; keep it off the event loop.
        await run_in_threadpool(
            webhooks.receive,
            db,
            raw,
            signatures=request.headers.getlist("signature"),
            timestamp=request.headers.get("timestamputc"),
        )
    except webhooks.InvalidWebhookError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None
    return WebhookAck()
