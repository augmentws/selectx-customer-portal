import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Technician(Base):
    """A PestPac technician, resolved from GET /lookups/Employees/technicians/{techId} the first
    time a service order references them. Only identifying fields are kept: no email, phone,
    birth date, emergency contacts, or access settings."""

    __tablename__ = "technicians"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "pestpac_tech_id", name="uq_technicians_operator_id_pestpac_tech_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pestpac_tech_id: Mapped[int] = mapped_column(Integer)
    pestpac_employee_id: Mapped[int | None] = mapped_column(Integer)
    # Matches service orders' Tech1 and notes' CreatedByUser.
    username: Mapped[str | None] = mapped_column(String(100), index=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    pestpac_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ServiceOrder(Base):
    """Our permanent copy of a PestPac service order for an onboarded bill-to.

    Lifecycle: open (`posted` false) -> worked (`posted` true, `posted_at` set when we first see
    it) -> billed (PestPac stops returning it; `closed_at` set). The row is never deleted: once
    billed, PestPac no longer shows the order, so this copy is the service history.
    """

    __tablename__ = "service_orders"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "pestpac_order_id", name="uq_service_orders_operator_id_pestpac_order_id"
        ),
        ForeignKeyConstraint(
            ["bill_to_id", "operator_id"],
            ["bill_tos.id", "bill_tos.operator_id"],
            name="fk_service_orders_bill_to_operator",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    bill_to_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # Null when the order's LocationID isn't among the bill-to's synced locations.
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    pestpac_order_id: Mapped[int] = mapped_column(BigInteger)
    pestpac_location_id: Mapped[int] = mapped_column(BigInteger)
    order_number: Mapped[str | None] = mapped_column(String(50), index=True)
    service_code: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    # PestPac sends local wall-clock time without an offset; stored as-is.
    work_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    tech_name: Mapped[str | None] = mapped_column(String(100))
    tech_id: Mapped[int | None] = mapped_column(Integer)
    # Resolved from tech_id; null until the lookup succeeds (the raw fields above remain).
    technician_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("technicians.id", ondelete="SET NULL"), index=True
    )
    technician: Mapped[Technician | None] = relationship()
    location_instructions: Mapped[str | None] = mapped_column(Text)
    service_instructions: Mapped[str | None] = mapped_column(Text)
    order_instructions: Mapped[str | None] = mapped_column(Text)
    technician_comment: Mapped[str | None] = mapped_column(Text)

    # From the order's notes' associations once it has been invoiced.
    pestpac_invoice_id: Mapped[int | None] = mapped_column(BigInteger)
    posted: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pestpac_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def technician_name(self) -> str | None:
        """Resolved first/last name, falling back to PestPac's Tech1 username."""
        if self.technician is not None:
            full = " ".join(p for p in (self.technician.first_name, self.technician.last_name) if p)
            if full:
                return full
        return self.tech_name


class SyncJobKind(enum.StrEnum):
    bill_to_service_orders = "bill_to_service_orders"
    location_service_orders = "location_service_orders"
    # "Sync location": documents and conditions, on request.
    bill_to_location_sync = "bill_to_location_sync"
    location_sync = "location_sync"


class SyncJobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    partial = "partial"  # some locations failed; the rest were synced
    failed = "failed"


class SyncJob(Base):
    """Work for `python -m app.worker`, claimed with FOR UPDATE SKIP LOCKED."""

    __tablename__ = "sync_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SyncJobKind] = mapped_column(Enum(SyncJobKind, name="sync_job_kind"))
    status: Mapped[SyncJobStatus] = mapped_column(
        Enum(SyncJobStatus, name="sync_job_status"), default=SyncJobStatus.queued, index=True
    )
    bill_to_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bill_tos.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE")
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # {"locations_total", "locations_done", "failed_locations": [...], "orders": {...}}
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(String(1000))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
