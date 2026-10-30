"""inspection finding requests

Revision ID: b267622f15f3
Revises: 777212fafda6
Create Date: 2026-10-30 13:45:51.109418

The queue for extracting findings without a report (one row per waiting or failed service order),
and each company's opt-in, off by default.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b267622f15f3"
down_revision: str | Sequence[str] | None = "777212fafda6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "inspection_finding_requests",
        sa.Column("service_order_id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["tenants.id"],
            name=op.f("fk_inspection_finding_requests_operator_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_order_id"],
            ["service_orders.id"],
            name=op.f("fk_inspection_finding_requests_service_order_id_service_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("service_order_id", name=op.f("pk_inspection_finding_requests")),
    )
    op.create_index(
        op.f("ix_inspection_finding_requests_operator_id"),
        "inspection_finding_requests",
        ["operator_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inspection_finding_requests_requested_at"),
        "inspection_finding_requests",
        ["requested_at"],
        unique=False,
    )
    op.add_column(
        "companies",
        sa.Column(
            "extract_findings", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("companies", "extract_findings")
    op.drop_index(
        op.f("ix_inspection_finding_requests_requested_at"),
        table_name="inspection_finding_requests",
    )
    op.drop_index(
        op.f("ix_inspection_finding_requests_operator_id"),
        table_name="inspection_finding_requests",
    )
    op.drop_table("inspection_finding_requests")
