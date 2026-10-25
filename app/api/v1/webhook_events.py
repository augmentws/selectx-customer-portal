import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    GoCanvasRequest,
    SignatureStatus,
    WebhookEntity,
    WebhookEvent,
    WebhookEventStatus,
)
from app.schemas.webhooks import (
    GoCanvasRequestDetail,
    GoCanvasRequestPage,
    GoCanvasRequestRead,
    WebhookEventDetail,
    WebhookEventPage,
    WebhookEventRead,
)
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import gocanvas, tenancy, webhooks

router = APIRouter(tags=["webhooks"])


def _read(event: WebhookEvent) -> dict:
    fields = WebhookEventRead.model_fields.keys() - {"has_raw_body"}
    return {name: getattr(event, name) for name in fields} | {
        "has_raw_body": event.raw_body is not None
    }


@router.get("/operators/{operator_id}/webhook-events", response_model=WebhookEventPage)
def list_webhook_events(
    operator_id: uuid.UUID,
    entity: WebhookEntity | None = None,
    action: str | None = Query(default=None, max_length=20),
    event_status: WebhookEventStatus | None = Query(default=None, alias="status"),
    signature_status: SignatureStatus | None = None,
    entity_id: int | None = Query(default=None, ge=1, description="PestPac EntityId"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Stored PestPac webhook deliveries, newest first. Deliveries dropped by the bill-to rule
    are never stored, so they don't appear here."""
    operator = tenancy.get_operator(db, operator_id)
    if operator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(Perm.webhooks_read, operator.id, read_perm=Perm.operators_read)
    rows, total = webhooks.list_events(
        db,
        operator.id,
        entity=entity,
        action=action,
        status=event_status,
        signature_status=signature_status,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
    return WebhookEventPage(
        items=[WebhookEventRead(**_read(e)) for e in rows], total=total, limit=limit, offset=offset
    )


@router.get("/webhook-events/{event_id}", response_model=WebhookEventDetail)
def get_webhook_event(
    event_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    event = db.get(WebhookEvent, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(Perm.webhooks_read, event.operator_id, read_perm=Perm.operators_read)
    bill_to_id, location_id = webhooks.linked_records(db, event)
    return WebhookEventDetail(
        **_read(event),
        raw_body=event.raw_body,
        raw_body_purged_at=event.raw_body_purged_at,
        bill_to_id=bill_to_id,
        location_id=location_id,
    )


def _gocanvas_read(request: GoCanvasRequest) -> dict:
    fields = GoCanvasRequestRead.model_fields.keys() - {"has_raw_body"}
    return {name: getattr(request, name) for name in fields} | {
        "has_raw_body": request.raw_body is not None
    }


@router.get("/operators/{operator_id}/gocanvas-requests", response_model=GoCanvasRequestPage)
def list_gocanvas_requests(
    operator_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Requests received at the operator's GoCanvas webhook URL, newest first."""
    operator = tenancy.get_operator(db, operator_id)
    if operator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(Perm.webhooks_read, operator.id, read_perm=Perm.operators_read)
    rows, total = gocanvas.list_requests(db, operator.id, limit=limit, offset=offset)
    return GoCanvasRequestPage(
        items=[GoCanvasRequestRead(**_gocanvas_read(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/gocanvas-requests/{request_id}", response_model=GoCanvasRequestDetail)
def get_gocanvas_request(
    request_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    request = db.get(GoCanvasRequest, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(Perm.webhooks_read, request.operator_id, read_perm=Perm.operators_read)
    return GoCanvasRequestDetail(
        **_gocanvas_read(request),
        headers=request.headers,
        raw_body=request.raw_body,
        raw_body_purged_at=request.raw_body_purged_at,
    )
