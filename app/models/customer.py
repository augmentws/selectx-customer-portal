import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Company(Base):
    """Our own customer entity; PestPac has no equivalent. Groups one or more bill-tos."""

    __tablename__ = "companies"
    __table_args__ = (
        # Target for bill_tos' composite FK, which keeps a bill-to inside its company's operator.
        UniqueConstraint("id", "operator_id", name="uq_companies_id_operator_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillTo(Base):
    """A PestPac bill-to onboarded to the portal. Onboarding happens at this level; it may
    cover a single location, a region, or a whole company (see `description`)."""

    __tablename__ = "bill_tos"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "pestpac_bill_to_id", name="uq_bill_tos_operator_id_pestpac_bill_to_id"
        ),
        ForeignKeyConstraint(
            ["company_id", "operator_id"],
            ["companies.id", "companies.operator_id"],
            name="fk_bill_tos_company_operator",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(index=True)
    pestpac_bill_to_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    onboarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    onboarded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    # Identifying details copied from PestPac GET /BillTos/{id} on onboarding and refresh.
    # Deliberately no financial fields or raw snapshot: balances and credit data go stale.
    pestpac_bill_to_code: Mapped[str | None] = mapped_column(String(50))
    pestpac_company: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(200))
    address2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(50))
    zip: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(50))
    pestpac_type: Mapped[str | None] = mapped_column(String(100))
    pestpac_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
