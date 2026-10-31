"""location areas

Revision ID: bdfae6719981
Revises: b267622f15f3
Create Date: 2026-10-30 15:47:07.993852

Each location's areas as PestPac defines them (a tree, synced by "Sync location"), and the area
a condition names, linked by its AreaID once the areas are synced.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bdfae6719981"
down_revision: str | Sequence[str] | None = "b267622f15f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "location_areas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("pestpac_area_id", sa.BigInteger(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("pestpac_location_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("pestpac_parent_id", sa.BigInteger(), nullable=True),
        sa.Column("depth", sa.SmallInteger(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_with_path", sa.String(length=500), nullable=True),
        sa.Column("area_type", sa.String(length=50), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_inspection_date", sa.DateTime(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pestpac_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_location_areas_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["tenants.id"],
            name=op.f("fk_location_areas_operator_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["location_areas.id"],
            name=op.f("fk_location_areas_parent_id_location_areas"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_location_areas")),
        sa.UniqueConstraint(
            "operator_id", "pestpac_area_id", name="uq_location_areas_operator_id_pestpac_area_id"
        ),
    )
    op.create_index(
        op.f("ix_location_areas_location_id"), "location_areas", ["location_id"], unique=False
    )
    op.create_index(
        op.f("ix_location_areas_operator_id"), "location_areas", ["operator_id"], unique=False
    )
    op.create_index(
        op.f("ix_location_areas_parent_id"), "location_areas", ["parent_id"], unique=False
    )
    op.add_column("conditions", sa.Column("location_area_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_conditions_location_area_id"), "conditions", ["location_area_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_conditions_location_area_id_location_areas"),
        "conditions",
        "location_areas",
        ["location_area_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_conditions_location_area_id_location_areas"), "conditions", type_="foreignkey"
    )
    op.drop_index(op.f("ix_conditions_location_area_id"), table_name="conditions")
    op.drop_column("conditions", "location_area_id")
    op.drop_index(op.f("ix_location_areas_parent_id"), table_name="location_areas")
    op.drop_index(op.f("ix_location_areas_operator_id"), table_name="location_areas")
    op.drop_index(op.f("ix_location_areas_location_id"), table_name="location_areas")
    op.drop_table("location_areas")
