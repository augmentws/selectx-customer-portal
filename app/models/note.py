import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.service_order import Technician


class Note(Base):
    """A PestPac note. One row per NoteID, mirroring PestPac: a note can be associated with
    several objects at once (location, order, invoice, ...).

    Objects we model get real foreign keys; every association is also kept as its raw PestPac
    id, so modelling another object later is a backfill, not a re-fetch. Associations come from
    GET /Notes/{id}; the location notes list doesn't include them.
    """

    __tablename__ = "notes"
    __table_args__ = (
        UniqueConstraint(
            "operator_id", "pestpac_note_id", name="uq_notes_operator_id_pestpac_note_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    pestpac_note_id: Mapped[int] = mapped_column(BigInteger)
    # PestPac local wall-clock time, stored as-is (like service orders' WorkDate).
    note_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    note_code: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user: Mapped[str | None] = mapped_column(String(100))
    show_on_portal: Mapped[bool] = mapped_column(Boolean, default=False)
    alert_expiration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    # Links to what we model.
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    bill_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bill_tos.id", ondelete="SET NULL"), index=True
    )
    service_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_orders.id", ondelete="SET NULL"), index=True
    )
    created_by_technician_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("technicians.id", ondelete="SET NULL")
    )
    created_by_technician: Mapped[Technician | None] = relationship()

    # Raw PestPac associations (from GET /Notes/{id}).
    pestpac_location_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    pestpac_bill_to_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_order_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    pestpac_invoice_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_contact_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_task_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_sales_lead_id: Mapped[int | None] = mapped_column(BigInteger)
    pestpac_call_id: Mapped[int | None] = mapped_column(BigInteger)

    pestpac_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    associations_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def created_by_name(self) -> str | None:
        """The author's name when they're a known technician, else PestPac's username."""
        tech = self.created_by_technician
        if tech is not None:
            full = " ".join(p for p in (tech.first_name, tech.last_name) if p)
            if full:
                return full
        return self.created_by_user
