import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StoredFile(Base):
    """An object in object storage. Every stored file gets one row; the records it belongs to
    (inspection photos so far) point here with a `file_id` and keep their own details.

    Served by GET /v1/files/{id} to callers holding `files:read` for `company_id` (a company
    grant counts only for its own company). A file whose company isn't known yet (an
    inspection not linked to a location) needs `files:read` on the operator."""

    __tablename__ = "stored_files"
    __table_args__ = (
        # Keeps a file's company inside its operator.
        ForeignKeyConstraint(
            ["company_id", "operator_id"],
            ["companies.id", "companies.operator_id"],
            name="fk_stored_files_company_operator",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    # What stored it, e.g. "gocanvas_photo".
    source: Mapped[str] = mapped_column(String(50))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    original_name: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
