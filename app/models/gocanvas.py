import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.pestpac import ConnectionStatus


class GoCanvasConnection(Base):
    """An operator's GoCanvas API access (OAuth client credentials). The client secret is Fernet
    ciphertext (app.security.secrets) and is never returned by the API."""

    __tablename__ = "gocanvas_connections"

    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    client_id: Mapped[str] = mapped_column(String(255))
    client_secret_enc: Mapped[str] = mapped_column(Text)

    status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, name="gocanvas_connection_status"),
        default=ConnectionStatus.unverified,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))

    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
