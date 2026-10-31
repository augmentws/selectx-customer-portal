import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.zone import zone_check


class AreaType(Base):
    """A PestPac area type (GET /lookups/AreaTypes), keyed by AreaTypeID, and the zone (app.models.
    Zone) its areas count as: the operator's area mapping. Areas carry their type's Code
    (`location_areas.area_type`). Synced on request from the operator's Area mapping tab; a type
    PestPac stops listing gets `removed_at` and keeps its zone."""

    __tablename__ = "area_types"
    __table_args__ = (
        UniqueConstraint(
            "operator_id",
            "pestpac_area_type_id",
            name="uq_area_types_operator_id_pestpac_area_type_id",
        ),
        CheckConstraint(zone_check("zone"), name="zone_values"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pestpac_area_type_id: Mapped[int] = mapped_column(BigInteger)
    code: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(String(500))
    # Null: not mapped (its areas have no zone).
    zone: Mapped[str | None] = mapped_column(String(40))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pestpac_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ZoneLabel(Base):
    """An operator's display name for a zone, replacing its default name (DEFAULT_ZONE_NAMES)."""

    __tablename__ = "zone_labels"
    __table_args__ = (
        UniqueConstraint("operator_id", "zone", name="uq_zone_labels_operator_id_zone"),
        CheckConstraint(zone_check("zone"), name="zone_values"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    zone: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
