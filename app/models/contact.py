import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ContactRole(enum.StrEnum):
    """A contact's role at the object it's linked to."""

    executive_team_director = "executive_team_director"
    team_director = "team_director"
    # The Leader Report's "Area Manager / Team Leader / Apprentice Team Leader".
    restaurant_leader = "restaurant_leader"
    # The restaurant's own phone and email.
    store = "store"


class Contact(Base):
    """A person or mailbox supplied by the customer (not PestPac's contact fields). One row per
    `(operator, source, source_key)`: the same Team Director across 40 stores is one contact
    with 40 links. Never hard-deleted; `removed_at` is set when no import links it any more."""

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("operator_id", "source", "source_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    # The customer they belong to.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(200))
    # Lower-cased.
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    # Where it came from, e.g. "restaurant_leader_report".
    source: Mapped[str] = mapped_column(String(50))
    # The dedupe key within the source: the email when there is one, else name and phone.
    source_key: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContactLink(Base):
    """A contact attached to exactly one object (a location or a bill-to) in a role. Another
    object type later is another nullable FK, the way `notes` does it."""

    __tablename__ = "contact_links"
    __table_args__ = (
        CheckConstraint("num_nonnulls(location_id, bill_to_id) = 1", name="one_object"),
        UniqueConstraint(
            "contact_id", "location_id", "bill_to_id", "role", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), index=True
    )
    contact: Mapped[Contact] = relationship()
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )
    bill_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bill_tos.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[ContactRole] = mapped_column(Enum(ContactRole, name="contact_role"))
    source: Mapped[str] = mapped_column(String(50))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Set when the next import from `source` no longer lists it.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
