import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WebhookEntity(enum.StrEnum):
    bill_to = "bill_to"
    employee = "employee"
    location = "location"
    note = "note"
    service_order = "service_order"


class SignatureStatus(enum.StrEnum):
    valid = "valid"
    invalid = "invalid"
    missing = "missing"  # no signature/timestamp headers
    no_secret = "no_secret"  # the operator has no webhook secret configured


class WebhookEventStatus(enum.StrEnum):
    received = "received"  # stored, not processed yet (all events, while handlers are stubs)
    processed = "processed"
    failed = "failed"


class WebhookEvent(Base):
    """A PestPac webhook delivery that matched the bill-to rule. Events that don't are never
    stored. The raw body (customer data) is cleared after WEBHOOK_RAW_RETENTION_DAYS; the rest
    of the row stays as the audit trail."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        # PestPac may redeliver; the same body signed at the same time is the same delivery.
        Index(
            "uq_webhook_events_delivery",
            "operator_id",
            "body_sha256",
            "pestpac_timestamp",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    entity: Mapped[WebhookEntity] = mapped_column(Enum(WebhookEntity, name="webhook_entity"))
    action: Mapped[str] = mapped_column(String(20))
    pestpac_entity_id: Mapped[int] = mapped_column(BigInteger)
    # The ids the bill-to rule matched on, when the body carries them.
    pestpac_bill_to_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    pestpac_location_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_timestamp: Mapped[str | None] = mapped_column(String(40))
    signature_status: Mapped[SignatureStatus] = mapped_column(
        Enum(SignatureStatus, name="webhook_signature_status")
    )
    body_sha256: Mapped[str] = mapped_column(String(64))
    raw_body: Mapped[str | None] = mapped_column(Text)
    raw_body_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[WebhookEventStatus] = mapped_column(
        Enum(WebhookEventStatus, name="webhook_event_status"),
        default=WebhookEventStatus.received,
        index=True,
    )
    error: Mapped[str | None] = mapped_column(String(1000))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
