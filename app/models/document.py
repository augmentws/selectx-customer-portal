import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.file import StoredFile


class Document(Base):
    """A PestPac document: one row per (DocumentType, DocumentID), since ids may repeat across
    types. Like notes, objects we model get real foreign keys and the raw PestPac ids are kept.

    The file itself lives in object storage under `storage_key`; until it's stored (or if it's
    too large, or the download failed) `storage_key` is null. Documents PestPac stops listing
    get `removed_at`; neither rows nor files are deleted.
    """

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "operator_id",
            "document_type",
            "pestpac_document_id",
            name="uq_documents_operator_id_document_type_pestpac_document_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    # PestPac's DocumentType: LocationDocument, Form, CallDocument, ConditionDocument, ...
    document_type: Mapped[str] = mapped_column(String(50))
    pestpac_document_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(String(500))
    file_name: Mapped[str | None] = mapped_column(String(500))
    # PestPac local wall-clock time, stored as-is (like service orders' WorkDate).
    document_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)
    starting_effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    ending_effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    is_tech_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    # PestPac's IncludeOn flags (service_orders, portal, mobile_app, ...), snake_cased.
    include_on: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Links to what we model.
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    service_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_orders.id", ondelete="SET NULL"), index=True
    )
    # Set for a condition's documents (from GET /Conditions/{id}).
    condition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conditions.id", ondelete="SET NULL"), index=True
    )
    # Raw PestPac ids.
    pestpac_location_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    pestpac_order_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_setup_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_issue_id: Mapped[int | None] = mapped_column(BigInteger)

    # The stored file (key, type, hash) is a `stored_files` row.
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stored_files.id", ondelete="RESTRICT"), index=True
    )
    file: Mapped[StoredFile | None] = relationship(lazy="selectin")
    # The file's size: also recorded for files too large to store.
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    # Why the file isn't stored (download failed, too large); cleared once it is.
    file_error: Mapped[str | None] = mapped_column(String(500))
    file_attempts: Mapped[int] = mapped_column(Integer, default=0)
    # PestPac can't send the file at all (its API gateway refuses bodies over 10 MB), so it
    # isn't tried again; file_error says why. The document row is kept.
    file_unavailable: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pestpac_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def has_file(self) -> bool:
        return self.file_id is not None

    @property
    def storage_key(self) -> str | None:
        return self.file.storage_key if self.file else None

    @property
    def content_type(self) -> str | None:
        return self.file.content_type if self.file else None
