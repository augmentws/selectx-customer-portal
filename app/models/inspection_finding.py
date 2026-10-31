"""Findings from a service visit, read out of the technician's notes by the LLM: what was
found and done, as data the dashboard can count. One current row per service order; the
vocabularies are defined in `app.services.inspection_findings`."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.zone import zone_check


class InspectionFinding(Base):
    """A visit's findings, replaced whenever they're read again (a new draft or extraction).
    Edits to a report's narrative never change them."""

    __tablename__ = "inspection_findings"
    __table_args__ = (
        CheckConstraint("source IN ('report_draft', 'extraction')", name="source_values"),
        CheckConstraint(
            "rodent_activity IN ('none', 'low', 'moderate', 'heavy')", name="rodent_activity_values"
        ),
        CheckConstraint("exclusion_status IN ('intact', 'compromised')", name="exclusion_values"),
        CheckConstraint(
            "sanitation_rating IN ('satisfactory', 'needs_improvement', 'poor')",
            name="sanitation_rating_values",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    service_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_orders.id", ondelete="RESTRICT"), unique=True
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    # The report whose draft produced them (source report_draft).
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reports.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[str] = mapped_column(String(20))

    visit_type: Mapped[str] = mapped_column(String(40))
    # Null when the notes don't say.
    rodent_activity: Mapped[str | None] = mapped_column(String(20))
    rodent_species: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    rodent_evidence: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    rodents_captured: Mapped[int | None] = mapped_column(Integer)
    activity_locations: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # The zones (app.models.Zone) of the activity locations, distinct.
    activity_zones: Mapped[list[str]] = mapped_column(
        ARRAY(Text), default=list, server_default="{}"
    )
    devices_serviced: Mapped[int | None] = mapped_column(Integer)
    exclusion_status: Mapped[str | None] = mapped_column(String(20))
    sanitation_rating: Mapped[str | None] = mapped_column(String(20))
    summary: Mapped[str | None] = mapped_column(Text)

    # How they were read: the serving model, the findings rules' version, token/cost usage.
    model: Mapped[str] = mapped_column(String(200))
    method_version: Mapped[int] = mapped_column(SmallInteger)
    usage: Mapped[dict | None] = mapped_column(JSONB)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list[InspectionFindingItem]] = relationship(
        back_populates="finding",
        cascade="all, delete-orphan",
        order_by="InspectionFindingItem.position",
    )


class InspectionFindingItem(Base):
    """One structural, sanitation, or other-pest finding of a visit. Replaced with the visit's
    findings."""

    __tablename__ = "inspection_finding_items"
    __table_args__ = (
        CheckConstraint("kind IN ('structural', 'sanitation', 'pest')", name="kind_values"),
        CheckConstraint("status IN ('open', 'in_progress', 'repaired')", name="status_values"),
        CheckConstraint("severity IN ('low', 'moderate', 'heavy')", name="severity_values"),
        CheckConstraint(zone_check("zone"), name="zone_values"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_findings.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(SmallInteger)
    # Structural and sanitation: the category; pest: the pest.
    category: Mapped[str] = mapped_column(String(60))
    location: Mapped[str | None] = mapped_column(Text)
    # Where it is, as a zone (app.models.Zone); null for findings read before zones.
    zone: Mapped[str | None] = mapped_column(String(40))
    issue: Mapped[str | None] = mapped_column(Text)
    # Structural only.
    status: Mapped[str | None] = mapped_column(String(20))
    # Sanitation and pest only.
    severity: Mapped[str | None] = mapped_column(String(20))

    finding: Mapped[InspectionFinding] = relationship(back_populates="items")


class InspectionFindingRequest(Base):
    """A service order waiting for its findings to be extracted without a report (the worker's
    queue; `app/services/findings_extraction.py`). Deleted once handled; a failure stays, with
    `requested_at` cleared and the error, until it's requeued."""

    __tablename__ = "inspection_finding_requests"

    service_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_orders.id", ondelete="RESTRICT"), primary_key=True
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    # Null once it failed: not queued.
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    error: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
