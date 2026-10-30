import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    false,
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
    # Extract each worked order's findings from its notes (LLM) when it's posted. Off by
    # default: it sends the company's notes to OpenRouter.
    extract_findings: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillTo(Base):
    """A PestPac bill-to onboarded to the portal. Onboarding happens at this level; it may
    cover a single location, a region, or a whole company (see `description`)."""

    __tablename__ = "bill_tos"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "pestpac_bill_to_id", name="uq_bill_tos_operator_id_pestpac_bill_to_id"
        ),
        # Target for locations' composite FK, which keeps a location inside its bill-to's operator.
        UniqueConstraint("id", "operator_id", name="uq_bill_tos_id_operator_id"),
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


class Location(Base):
    """A PestPac service location under an onboarded bill-to, synced from
    GET /BillTos/{id}/locations/pageable. `pestpac_company` (e.g. "CHIPOTLE - STORE #2301") is
    the location's name. Contact names and user-defined fields are deliberately not stored.
    `description` is ours (e.g. the customer's store name), never written by PestPac syncs."""

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint(
            "operator_id",
            "pestpac_location_id",
            name="uq_locations_operator_id_pestpac_location_id",
        ),
        ForeignKeyConstraint(
            ["bill_to_id", "operator_id"],
            ["bill_tos.id", "bill_tos.operator_id"],
            name="fk_locations_bill_to_operator",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    bill_to_id: Mapped[uuid.UUID] = mapped_column(index=True)
    pestpac_location_id: Mapped[int] = mapped_column(BigInteger)
    pestpac_location_code: Mapped[str | None] = mapped_column(String(50))
    pestpac_company: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(200))
    address2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(50))
    zip: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(320))
    pestpac_type: Mapped[str | None] = mapped_column(String(100))
    account_type: Mapped[str | None] = mapped_column(String(50))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    pestpac_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Not from PestPac: filled by our own imports (the Restaurant Leader Report's store name).
    description: Mapped[str | None] = mapped_column(String(300))
    # Set when PestPac stops listing this location under its bill-to. Kept, not deleted,
    # because service orders will reference locations.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pestpac_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
