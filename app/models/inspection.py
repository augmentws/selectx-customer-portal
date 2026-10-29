"""GoCanvas inspections: form definitions, submissions, and their parsed contents.

Two layers. Shared by every inspection kind: the form definition (`inspection_forms`, with its
zones and fields derived from GoCanvas sections and entries), the submission header, and every
response as received (`inspection_responses`, so nothing is lost when parsing changes). Then
typed tables per kind; only risk inspections have them so far (`risk_inspection_*`).
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.file import StoredFile


class InspectionKind(enum.StrEnum):
    standard = "standard"
    risk = "risk"


class InspectionForm(Base):
    """A GoCanvas form definition (GET /forms/{id}), per operator. GoCanvas keeps the form id
    across published versions, so re-importing replaces the zones and fields and bumps
    `version`; older submissions may hold option values the current version no longer has."""

    __tablename__ = "inspection_forms"
    __table_args__ = (
        UniqueConstraint(
            "operator_id",
            "gocanvas_form_id",
            name="uq_inspection_forms_operator_id_gocanvas_form_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    gocanvas_form_id: Mapped[int] = mapped_column(BigInteger)
    gocanvas_root_version_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[InspectionKind] = mapped_column(Enum(InspectionKind, name="inspection_kind"))
    name: Mapped[str] = mapped_column(String(300))
    version: Mapped[int | None] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSONB)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    zones: Mapped[list[InspectionFormZone]] = relationship(
        back_populates="form", cascade="all, delete-orphan", order_by="InspectionFormZone.position"
    )
    fields: Mapped[list[InspectionFormField]] = relationship(
        back_populates="form", cascade="all, delete-orphan", order_by="InspectionFormField.position"
    )


class InspectionFormZone(Base):
    """A GoCanvas section that is an inspection zone (it asks "Has this zone been inspected?")."""

    __tablename__ = "inspection_form_zones"
    __table_args__ = (
        UniqueConstraint("form_id", "zone_key", name="uq_inspection_form_zones_form_id_zone_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_forms.id", ondelete="CASCADE"), index=True
    )
    gocanvas_section_id: Mapped[int] = mapped_column(BigInteger)
    zone_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(SmallInteger)

    form: Mapped[InspectionForm] = relationship(back_populates="zones")


class InspectionFormField(Base):
    """A GoCanvas entry, mapped to a `field_key` by its label (labels repeat per zone, so the
    zone tells them apart). Unmatched entries get no key; their responses are still stored."""

    __tablename__ = "inspection_form_fields"
    __table_args__ = (
        UniqueConstraint("form_id", "entry_id", name="uq_inspection_form_fields_form_id_entry_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_forms.id", ondelete="CASCADE"), index=True
    )
    entry_id: Mapped[int] = mapped_column(BigInteger)
    gocanvas_section_id: Mapped[int] = mapped_column(BigInteger)
    # Null for header, summary, and material fields.
    zone_key: Mapped[str | None] = mapped_column(String(100))
    field_key: Mapped[str | None] = mapped_column(String(100))
    entry_type_id: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(500))
    export_label: Mapped[str | None] = mapped_column(String(100))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    # Value list options, trimmed (GoCanvas keeps trailing spaces in some).
    options: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # GoCanvas has no flag for this: lists without a minimum/maximum are the "check all" ones.
    multi_select: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer)

    form: Mapped[InspectionForm] = relationship(back_populates="fields")


class InspectionSubmission(Base):
    """One GoCanvas submission. A revision keeps its submission id, so it replaces the parsed
    rows; an older revision arriving late is ignored. `raw_payload` is kept because
    `gocanvas_requests` bodies are purged after the retention window."""

    __tablename__ = "inspection_submissions"
    __table_args__ = (
        UniqueConstraint(
            "operator_id",
            "gocanvas_submission_id",
            name="uq_inspection_submissions_operator_id_gocanvas_submission_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_forms.id", ondelete="RESTRICT"), index=True
    )
    gocanvas_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gocanvas_requests.id", ondelete="SET NULL")
    )
    # Linked by the work order number (a PestPac order number), else by the store name.
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), index=True
    )
    service_order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("service_orders.id", ondelete="SET NULL"), index=True
    )

    gocanvas_submission_id: Mapped[int] = mapped_column(BigInteger)
    gocanvas_form_id: Mapped[int] = mapped_column(BigInteger)
    submission_number: Mapped[str | None] = mapped_column(String(50))
    client_guid: Mapped[str | None] = mapped_column(String(100))
    device_guid: Mapped[str | None] = mapped_column(String(100))
    gocanvas_user_id: Mapped[int | None] = mapped_column(BigInteger)
    gocanvas_department_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str | None] = mapped_column(String(50))
    is_revision: Mapped[bool] = mapped_column(Boolean, default=False)
    gocanvas_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    inspector_name: Mapped[str | None] = mapped_column(String(200))
    # The form's Date and Time: the store's wall-clock time, stored as-is.
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    store_label: Mapped[str | None] = mapped_column(String(200))
    store_number: Mapped[str | None] = mapped_column(String(50), index=True)
    address: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    work_order_ref: Mapped[str | None] = mapped_column(String(100))

    raw_payload: Mapped[dict] = mapped_column(JSONB)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    # Values the parser couldn't type: [{entry_id, field_key, value, issue}].
    parse_warnings: Mapped[list] = mapped_column(JSONB, default=list)
    unmapped_entry_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), default=list)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    form: Mapped[InspectionForm] = relationship()
    responses: Mapped[list[InspectionResponse]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="InspectionResponse.position",
    )
    risk_zones: Mapped[list[RiskInspectionZone]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="RiskInspectionZone.position",
    )
    risk_materials: Mapped[list[RiskInspectionMaterial]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )
    risk_summary: Mapped[RiskInspectionSummary | None] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )
    # Not cleared when a revision is parsed: photos are fetched separately and kept.
    photo_values: Mapped[list[InspectionPhotoValue]] = relationship(
        back_populates="submission", cascade="all, delete-orphan"
    )


class InspectionResponse(Base):
    """One response exactly as GoCanvas sent it, with the field map's keys resolved."""

    __tablename__ = "inspection_responses"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "entry_id", name="uq_inspection_responses_submission_id_entry_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_submissions.id", ondelete="CASCADE"), index=True
    )
    gocanvas_response_id: Mapped[int] = mapped_column(BigInteger)
    entry_id: Mapped[int] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(Integer)
    response_type: Mapped[str] = mapped_column(String(50))
    label: Mapped[str | None] = mapped_column(String(500))
    export_label: Mapped[str | None] = mapped_column(String(100))
    displayed: Mapped[bool] = mapped_column(Boolean)
    # Text values; non-text values (photo lists) go in value_json.
    value: Mapped[str | None] = mapped_column(Text)
    value_json: Mapped[dict | list | None] = mapped_column(JSONB)
    zone_key: Mapped[str | None] = mapped_column(String(100))
    field_key: Mapped[str | None] = mapped_column(String(100))

    submission: Mapped[InspectionSubmission] = relationship(back_populates="responses")


class InspectionPhotoValue(Base):
    """A photo field's answer (a Multi Photo response that has images). The submission only
    says "Binary data is not displayed"; GET /submissions/{id}/values/{value_id} returns a zip
    of the images, stored as `inspection_photos`. Fetched once (again when a revision changes
    the submission). A value a later revision drops gets `removed_at`; never deleted."""

    __tablename__ = "inspection_photo_values"
    __table_args__ = (
        UniqueConstraint(
            "submission_id",
            "gocanvas_value_id",
            name="uq_inspection_photo_values_submission_id_gocanvas_value_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_submissions.id", ondelete="CASCADE"), index=True
    )
    # The response's id in the submission.
    gocanvas_value_id: Mapped[int] = mapped_column(BigInteger)
    entry_id: Mapped[int] = mapped_column(BigInteger)
    zone_key: Mapped[str | None] = mapped_column(String(100))
    # pest, sanitation, structural, or additional (from the field map); null if unmapped.
    category: Mapped[str | None] = mapped_column(String(50))
    label: Mapped[str | None] = mapped_column(String(500))
    fetch_attempts: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_error: Mapped[str | None] = mapped_column(String(500))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    submission: Mapped[InspectionSubmission] = relationship(back_populates="photo_values")
    photos: Mapped[list[InspectionPhoto]] = relationship(
        back_populates="photo_value",
        cascade="all, delete-orphan",
        order_by="InspectionPhoto.position",
    )


class InspectionPhoto(Base):
    """One image from a photo value's zip. The object itself is a `stored_files` row."""

    __tablename__ = "inspection_photos"
    __table_args__ = (
        UniqueConstraint(
            "photo_value_id", "position", name="uq_inspection_photos_photo_value_id_position"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    photo_value_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_photo_values.id", ondelete="CASCADE"), index=True
    )
    # 1-based, from the zip entry's name ("Images_of_Pest_Activity_26574236658_1.jpeg").
    position: Mapped[int] = mapped_column(SmallInteger)
    file_name: Mapped[str] = mapped_column(String(300))
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stored_files.id", ondelete="RESTRICT"), index=True
    )

    photo_value: Mapped[InspectionPhotoValue] = relationship(back_populates="photos")
    file: Mapped[StoredFile] = relationship()


class RiskInspectionZone(Base):
    """One zone of a risk inspection: the PDF's station details and notes. Zone-specific
    questions (dumpster, ceiling, mall, ...) go in `attributes`. The zone summary (inspected,
    with/without activity) is derived, not stored."""

    __tablename__ = "risk_inspection_zones"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "zone_key", name="uq_risk_inspection_zones_submission_id_zone_key"
        ),
        CheckConstraint("inspected IN ('yes', 'no', 'n/a')", name="inspected_values"),
        CheckConstraint("sanitation_risk BETWEEN 1 AND 5", name="sanitation_risk_range"),
        CheckConstraint("structural_risk BETWEEN 1 AND 5", name="structural_risk_range"),
        CheckConstraint("overall_risk BETWEEN 1 AND 5", name="overall_risk_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_submissions.id", ondelete="CASCADE"), index=True
    )
    zone_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(SmallInteger)
    inspected: Mapped[str | None] = mapped_column(String(10))
    all_areas_inspected: Mapped[bool | None] = mapped_column(Boolean)
    areas: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    doors_are: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    door_sweeps_ok: Mapped[bool | None] = mapped_column(Boolean)
    doors_aligned: Mapped[bool | None] = mapped_column(Boolean)
    rodent_activity: Mapped[bool | None] = mapped_column(Boolean)
    pest_activity: Mapped[bool | None] = mapped_column(Boolean)
    # Single-select in the current form; a list so a multi-select form fits too.
    pest_types: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    additional_notes: Mapped[str | None] = mapped_column(Text)
    pest_notes: Mapped[str | None] = mapped_column(Text)
    sanitation_notes: Mapped[str | None] = mapped_column(Text)
    structural_notes: Mapped[str | None] = mapped_column(Text)
    sanitation_risk: Mapped[int | None] = mapped_column(SmallInteger)
    structural_risk: Mapped[int | None] = mapped_column(SmallInteger)
    overall_risk: Mapped[int | None] = mapped_column(SmallInteger)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)

    submission: Mapped[InspectionSubmission] = relationship(back_populates="risk_zones")

    @property
    def has_activity(self) -> bool:
        return bool(self.rodent_activity or self.pest_activity)


class RiskInspectionSummary(Base):
    """A risk inspection's overall results (one per submission)."""

    __tablename__ = "risk_inspection_summaries"
    __table_args__ = (
        CheckConstraint("ramp_recommendation BETWEEN 1 AND 3", name="ramp_recommendation_range"),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_submissions.id", ondelete="CASCADE"), primary_key=True
    )
    # "RAMP 3" (older submissions send just "3").
    ramp_recommendation: Mapped[int | None] = mapped_column(SmallInteger)
    manager_summary: Mapped[str | None] = mapped_column(Text)
    material_notes: Mapped[str | None] = mapped_column(Text)

    submission: Mapped[InspectionSubmission] = relationship(back_populates="risk_summary")


class RiskInspectionMaterial(Base):
    """Material used, from the Material Use section. The current form asks Yes/No; older
    submissions sent a quantity instead (in the unit the label names)."""

    __tablename__ = "risk_inspection_materials"
    __table_args__ = (
        UniqueConstraint(
            "submission_id",
            "material_key",
            name="uq_risk_inspection_materials_submission_id_material_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inspection_submissions.id", ondelete="CASCADE"), index=True
    )
    material_key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    used: Mapped[bool | None] = mapped_column(Boolean)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    raw_value: Mapped[str | None] = mapped_column(String(200))

    submission: Mapped[InspectionSubmission] = relationship(back_populates="risk_materials")
