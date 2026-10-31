import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Condition(Base):
    """A PestPac condition (issue) found at a location, keyed by IssueID. Like notes, objects we
    model get foreign keys and raw PestPac ids are kept.

    Synced while open; when PestPac stops listing one as open we fetch it once more to record
    its closing. Never deleted: one PestPac no longer has gets `removed_at`.
    """

    __tablename__ = "conditions"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "pestpac_issue_id", name="uq_conditions_operator_id_pestpac_issue_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pestpac_issue_id: Mapped[int] = mapped_column(BigInteger)

    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    service_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_orders.id", ondelete="SET NULL"), index=True
    )
    pestpac_location_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    pestpac_order_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_area_id: Mapped[int | None] = mapped_column(BigInteger)
    # The area PestPac's AreaID names, once the location's areas are synced.
    location_area_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("location_areas.id", ondelete="SET NULL"), index=True
    )

    area: Mapped[str | None] = mapped_column(String(200))
    specific_area: Mapped[str | None] = mapped_column(String(200))
    area_hierarchy: Mapped[str | None] = mapped_column(String(500))
    condition_type: Mapped[str | None] = mapped_column(String(100))
    condition: Mapped[str | None] = mapped_column(String(500))
    action: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    severity: Mapped[str | None] = mapped_column(String(50))
    responsibility: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(100))
    opened_by_user: Mapped[str | None] = mapped_column(String(100))
    # PestPac local wall-clock times, stored as-is (like service orders' WorkDate).
    date_opened: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    date_closed: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    last_inspected_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    inspections: Mapped[list[ConditionInspection]] = relationship(
        back_populates="condition",
        cascade="all, delete-orphan",
        order_by="ConditionInspection.detail_date",
    )

    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pestpac_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # When GET /Conditions/{id} (inspections, documents) was last read.
    details_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConditionInspection(Base):
    """One inspection of a condition. PestPac gives inspections no id, so a condition's
    inspections are replaced each time its details are fetched."""

    __tablename__ = "condition_inspections"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    condition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conditions.id", ondelete="CASCADE"), index=True
    )
    condition: Mapped[Condition] = relationship(back_populates="inspections")
    service_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_orders.id", ondelete="SET NULL")
    )
    pestpac_order_id: Mapped[int | None] = mapped_column(BigInteger)
    detail_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    username: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(50))
    comment: Mapped[str | None] = mapped_column(Text)
