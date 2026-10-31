import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LocationArea(Base):
    """An area of a location as PestPac defines it (GET /Locations/{id}/areas), keyed by AreaID:
    a tree ("Service Line/Food Prep -> Digital Make Line (DML)"). Conditions and devices name
    their area by AreaID. Synced by "Sync location"; never deleted: one PestPac stops listing
    gets `removed_at`."""

    __tablename__ = "location_areas"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "pestpac_area_id", name="uq_location_areas_operator_id_pestpac_area_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pestpac_area_id: Mapped[int] = mapped_column(BigInteger)
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    pestpac_location_id: Mapped[int] = mapped_column(BigInteger)
    # The parent area; null for a top-level area (PestPac's ParentID 0).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("location_areas.id", ondelete="SET NULL"), index=True
    )
    pestpac_parent_id: Mapped[int | None] = mapped_column(BigInteger)
    depth: Mapped[int] = mapped_column(SmallInteger)  # 1 for top-level areas
    name: Mapped[str] = mapped_column(String(200))
    name_with_path: Mapped[str | None] = mapped_column(String(500))
    area_type: Mapped[str | None] = mapped_column(String(50))  # e.g. KITCHEN, TRASH, EXTERIOR
    description: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean)
    # PestPac local wall-clock time; null for PestPac's "never" (1900-01-01).
    last_inspection_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pestpac_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
