import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConnectionStatus(enum.StrEnum):
    unverified = "unverified"
    verified = "verified"
    failed = "failed"


class PestPacConnection(Base):
    """An operator's PestPac API access. Secret columns hold Fernet ciphertext
    (app.security.secrets); they are never returned by the API."""

    __tablename__ = "pestpac_connections"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    base_url: Mapped[str] = mapped_column(String(255))
    client_id: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    client_secret_enc: Mapped[str] = mapped_column(Text)
    password_enc: Mapped[str] = mapped_column(Text)
    api_key_enc: Mapped[str] = mapped_column(Text)
    api_key_last4: Mapped[str] = mapped_column(String(4))
    # Signs webhook deliveries (HMAC-SHA256). Optional; unsigned events are flagged, not refused.
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text)

    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, name="pestpac_connection_status"),
        default=ConnectionStatus.unverified,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    # From GET /CompanySetup on successful verification.
    pestpac_company_id: Mapped[int | None] = mapped_column(Integer)
    pestpac_company_name: Mapped[str | None] = mapped_column(String(255))

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
