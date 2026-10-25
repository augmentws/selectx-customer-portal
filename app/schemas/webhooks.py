import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import SignatureStatus, WebhookEntity, WebhookEventStatus


class WebhookEventRead(BaseModel):
    """A stored webhook delivery, without its body."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operator_id: uuid.UUID
    entity: WebhookEntity
    action: str
    pestpac_entity_id: int
    pestpac_bill_to_id: int | None
    pestpac_location_id: int | None
    pestpac_timestamp: str | None  # the delivery's `timestamputc` header, as sent
    signature_status: SignatureStatus
    status: WebhookEventStatus
    error: str | None
    received_at: datetime
    processed_at: datetime | None
    client_ip: str | None
    forwarded_for: str | None
    user_agent: str | None
    sync_job_id: uuid.UUID | None
    has_raw_body: bool


class WebhookEventDetail(WebhookEventRead):
    # The delivery as received (customer data); null once cleared after the retention window.
    raw_body: str | None
    raw_body_purged_at: datetime | None
    # Our records for the PestPac ids, when we hold them.
    bill_to_id: uuid.UUID | None
    location_id: uuid.UUID | None


class WebhookEventPage(BaseModel):
    items: list[WebhookEventRead]
    total: int
    limit: int
    offset: int


class GoCanvasRequestRead(BaseModel):
    """A received GoCanvas request, without its body."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operator_id: uuid.UUID
    method: str
    query_string: str | None
    content_type: str | None
    client_ip: str | None
    forwarded_for: str | None
    user_agent: str | None
    body_size: int
    received_at: datetime
    has_raw_body: bool


class GoCanvasRequestDetail(GoCanvasRequestRead):
    headers: dict[str, str]
    # As received; null once cleared after the retention window.
    raw_body: str | None
    raw_body_purged_at: datetime | None


class GoCanvasRequestPage(BaseModel):
    items: list[GoCanvasRequestRead]
    total: int
    limit: int
    offset: int
