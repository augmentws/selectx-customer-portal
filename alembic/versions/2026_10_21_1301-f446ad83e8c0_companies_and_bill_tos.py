"""companies and bill_tos

Revision ID: f446ad83e8c0
Revises: 28172a6f9c15
Create Date: 2026-10-21 13:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f446ad83e8c0"
down_revision: str | Sequence[str] | None = "28172a6f9c15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["tenants.id"],
            name=op.f("fk_companies_operator_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_companies")),
        sa.UniqueConstraint("id", "operator_id", name="uq_companies_id_operator_id"),
    )
    op.create_index(op.f("ix_companies_operator_id"), "companies", ["operator_id"], unique=False)

    op.create_table(
        "bill_tos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("pestpac_bill_to_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "onboarded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("onboarded_by", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id", "operator_id"],
            ["companies.id", "companies.operator_id"],
            name="fk_bill_tos_company_operator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["onboarded_by"],
            ["users.id"],
            name=op.f("fk_bill_tos_onboarded_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["tenants.id"],
            name=op.f("fk_bill_tos_operator_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bill_tos")),
        sa.UniqueConstraint(
            "operator_id", "pestpac_bill_to_id", name="uq_bill_tos_operator_id_pestpac_bill_to_id"
        ),
    )
    op.create_index(op.f("ix_bill_tos_company_id"), "bill_tos", ["company_id"], unique=False)
    op.create_index(op.f("ix_bill_tos_operator_id"), "bill_tos", ["operator_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bill_tos_operator_id"), table_name="bill_tos")
    op.drop_index(op.f("ix_bill_tos_company_id"), table_name="bill_tos")
    op.drop_table("bill_tos")
    op.drop_index(op.f("ix_companies_operator_id"), table_name="companies")
    op.drop_table("companies")
