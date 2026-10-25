import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReportTemplate(Base):
    """A customer-specific HTML report template (Jinja, sandboxed), rendered to PDF with a
    location's data. A company may have any number. Written by platform admins only."""

    __tablename__ = "report_templates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "operator_id"],
            ["companies.id", "companies.operator_id"],
            name="fk_report_templates_company_operator",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000))
    # Full HTML document with inline CSS; images and fonts embedded as data: URIs.
    html: Mapped[str] = mapped_column(Text)
    # The fields a report from this template edits (and the LLM fills): a list of
    # app.schemas.reports.TemplateField, as JSON. The HTML reads them as `fields.<key>`.
    fields: Mapped[list] = mapped_column(JSONB, default=list)
    # Instructions for drafting the LLM fields from a service order's notes; paired with the
    # HTML and fields because they only work together.
    prompt: Mapped[str | None] = mapped_column(Text)
    # OpenRouter model id for drafting; None uses OPENROUTER_DEFAULT_MODEL.
    llm_model: Mapped[str | None] = mapped_column(String(200))
    # Incremented whenever the HTML, fields, or prompt change.
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReportStatus(enum.StrEnum):
    draft = "draft"  # editable
    drafting = "drafting"  # the worker is drafting the narrative fields
    final = "final"  # PDF generated and stored; locked (revise to change)
    # A final version replaced by a newer final one: its PDF is kept, but only the order's
    # newest version is final.
    superseded = "superseded"


class Report(Base):
    """A report for one service order: the data that went into it (`data`, JSON) and, once
    final, the generated PDF in object storage. Kept separately so the PDF can always be
    traced to exactly what produced it. Never deleted; a change after finalizing is a new
    revision.

    `data` holds `context` (a snapshot of location, order, and conditions taken when the report
    was started), `fields` (values for the template's fields), `notes` (the candidate notes
    and which are selected for drafting), and `photos` (candidate photos: selected, caption,
    order).
    """

    __tablename__ = "reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "operator_id"],
            ["companies.id", "companies.operator_id"],
            name="fk_reports_company_operator",
            ondelete="RESTRICT",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    operator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(index=True)
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    service_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_orders.id", ondelete="RESTRICT"), index=True
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("report_templates.id", ondelete="RESTRICT")
    )
    # The template version the report was started from (and is rendered with).
    template_version: Mapped[int] = mapped_column(Integer)
    # The report this one revises; revisions count up from 1.
    revises_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reports.id", ondelete="RESTRICT")
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status"), default=ReportStatus.draft, index=True
    )
    data: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Narrative drafting (LLM).
    draft_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    draft_error: Mapped[str | None] = mapped_column(String(1000))
    # Model and token/cost usage of the last draft.
    draft_usage: Mapped[dict | None] = mapped_column(JSONB)

    # The generated PDF.
    pdf_storage_key: Mapped[str | None] = mapped_column(String(500))
    pdf_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
