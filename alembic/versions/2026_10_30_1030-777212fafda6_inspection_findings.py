"""inspection findings

Revision ID: 777212fafda6
Revises: a6e2363f1127
Create Date: 2026-10-30 10:30:37.155162

A service visit's findings, read from the technician's notes by the LLM when a report is
drafted: one row per service order, with its structural, sanitation, and pest items.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "777212fafda6"
down_revision: str | Sequence[str] | None = "a6e2363f1127"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "inspection_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("service_order_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("visit_type", sa.String(length=40), nullable=False),
        sa.Column("rodent_activity", sa.String(length=20), nullable=True),
        sa.Column("rodent_species", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("rodent_evidence", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("rodents_captured", sa.Integer(), nullable=True),
        sa.Column("activity_locations", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("devices_serviced", sa.Integer(), nullable=True),
        sa.Column("exclusion_status", sa.String(length=20), nullable=True),
        sa.Column("sanitation_rating", sa.String(length=20), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("method_version", sa.SmallInteger(), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "exclusion_status IN ('intact', 'compromised')",
            name=op.f("ck_inspection_findings_exclusion_values"),
        ),
        sa.CheckConstraint(
            "rodent_activity IN ('none', 'low', 'moderate', 'heavy')",
            name=op.f("ck_inspection_findings_rodent_activity_values"),
        ),
        sa.CheckConstraint(
            "sanitation_rating IN ('satisfactory', 'needs_improvement', 'poor')",
            name=op.f("ck_inspection_findings_sanitation_rating_values"),
        ),
        sa.CheckConstraint(
            "source IN ('report_draft', 'extraction')",
            name=op.f("ck_inspection_findings_source_values"),
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_inspection_findings_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["tenants.id"],
            name=op.f("fk_inspection_findings_operator_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reports.id"],
            name=op.f("fk_inspection_findings_report_id_reports"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_order_id"],
            ["service_orders.id"],
            name=op.f("fk_inspection_findings_service_order_id_service_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inspection_findings")),
        sa.UniqueConstraint(
            "service_order_id", name=op.f("uq_inspection_findings_service_order_id")
        ),
    )
    op.create_index(
        op.f("ix_inspection_findings_location_id"),
        "inspection_findings",
        ["location_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inspection_findings_operator_id"),
        "inspection_findings",
        ["operator_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inspection_findings_report_id"), "inspection_findings", ["report_id"], unique=False
    )
    op.create_table(
        "inspection_finding_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("issue", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.CheckConstraint(
            "kind IN ('structural', 'sanitation', 'pest')",
            name=op.f("ck_inspection_finding_items_kind_values"),
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'moderate', 'heavy')",
            name=op.f("ck_inspection_finding_items_severity_values"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'repaired')",
            name=op.f("ck_inspection_finding_items_status_values"),
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["inspection_findings.id"],
            name=op.f("fk_inspection_finding_items_finding_id_inspection_findings"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inspection_finding_items")),
    )
    op.create_index(
        op.f("ix_inspection_finding_items_finding_id"),
        "inspection_finding_items",
        ["finding_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_inspection_finding_items_finding_id"), table_name="inspection_finding_items"
    )
    op.drop_table("inspection_finding_items")
    op.drop_index(op.f("ix_inspection_findings_report_id"), table_name="inspection_findings")
    op.drop_index(op.f("ix_inspection_findings_operator_id"), table_name="inspection_findings")
    op.drop_index(op.f("ix_inspection_findings_location_id"), table_name="inspection_findings")
    op.drop_table("inspection_findings")
