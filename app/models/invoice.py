import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.customer import Location
from app.models.service_order import ServiceOrder, Technician


class Invoice(Base):
    """A PestPac invoice for an onboarded bill-to, from GET /Invoices/{id} (fetched when its
    webhook arrives). Whitelisted fields only: amounts are kept (billing), but no tax details,
    contact names, technician pay, user-defined fields, or the raw response. Never deleted."""

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "pestpac_invoice_id", name="uq_invoices_operator_id_pestpac_invoice_id"
        ),
        ForeignKeyConstraint(
            ["bill_to_id", "operator_id"],
            ["bill_tos.id", "bill_tos.operator_id"],
            name="fk_invoices_bill_to_operator",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    bill_to_id: Mapped[uuid.UUID] = mapped_column(index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    service_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_orders.id", ondelete="SET NULL"), index=True
    )
    # Position-1 technician only, linked by TechID.
    technician_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("technicians.id", ondelete="SET NULL"), index=True
    )
    pestpac_invoice_id: Mapped[int] = mapped_column(BigInteger)
    pestpac_location_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_bill_to_id: Mapped[int] = mapped_column(BigInteger)
    pestpac_setup_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_order_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    pestpac_tech_id: Mapped[int | None] = mapped_column(Integer)
    invoice_number: Mapped[str | None] = mapped_column(String(50), index=True)
    order_number: Mapped[str | None] = mapped_column(String(50))
    service_code: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    balance: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    service_fee_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # PestPac local wall-clock times, stored as-is.
    invoice_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)
    work_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    time_range: Mapped[str | None] = mapped_column(String(50))
    duration: Mapped[int | None] = mapped_column(Integer)  # minutes
    invoice_type: Mapped[str | None] = mapped_column(String(50))
    order_type: Mapped[str | None] = mapped_column(String(50))
    origin: Mapped[str | None] = mapped_column(String(50))
    location_instructions: Mapped[str | None] = mapped_column(Text)
    service_instructions: Mapped[str | None] = mapped_column(Text)
    order_instructions: Mapped[str | None] = mapped_column(Text)
    technician_comment: Mapped[str | None] = mapped_column(Text)
    batch_number: Mapped[int | None] = mapped_column(BigInteger)
    # Set when a delete webhook arrives or PestPac no longer has it.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pestpac_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list[InvoiceLine]] = relationship(
        order_by="InvoiceLine.position", cascade="all, delete-orphan"
    )
    technician: Mapped[Technician | None] = relationship()
    service_order: Mapped[ServiceOrder | None] = relationship()
    location: Mapped[Location | None] = relationship()

    @property
    def technician_name(self) -> str | None:
        if self.technician is None:
            return None
        return " ".join(
            p for p in (self.technician.first_name, self.technician.last_name) if p
        ) or (self.technician.username)


class InvoiceLine(Base):
    """An invoice's LineItems. PestPac gives them no id, so they're replaced on every fetch."""

    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)  # order in PestPac's list, from 1
    service_code: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    extended_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    taxable: Mapped[bool | None] = mapped_column(Boolean)
    gl_code: Mapped[str | None] = mapped_column(String(50))
