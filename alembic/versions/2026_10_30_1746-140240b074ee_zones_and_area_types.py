"""zones and area types

Revision ID: 140240b074ee
Revises: bdfae6719981
Create Date: 2026-10-30 17:46:57.844832

The fixed zones (app.models.Zone) on findings (each item's zone, and the zones of the activity
locations), PestPac's area types with the zone each maps to, and operators' display names for the
zones.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

ZONES = (
    "exterior_perimeter",
    "dumpster_waste",
    "receiving_delivery",
    "dry_food_storage",
    "food_preparation",
    "service_line",
    "dishwashing_drains",
    "bar_beverage",
    "dining_guest",
    "restrooms",
    "offices_employee",
    "mechanical_utility",
    "basement",
    "ceiling_voids",
    "shared_structures",
    "other",
)
ZONE_CHECK = "zone IN ({})".format(", ".join(f"'{z}'" for z in ZONES))

# revision identifiers, used by Alembic.
revision: str = "140240b074ee"
down_revision: str | Sequence[str] | None = "bdfae6719981"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "area_types",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("pestpac_area_type_id", sa.BigInteger(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("zone", sa.String(length=40), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pestpac_fetched_at", sa.DateTime(timezone=True), nullable=False),
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
            ZONE_CHECK,
            name=op.f("ck_area_types_zone_values"),
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["tenants.id"],
            name=op.f("fk_area_types_operator_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_area_types")),
        sa.UniqueConstraint(
            "operator_id",
            "pestpac_area_type_id",
            name="uq_area_types_operator_id_pestpac_area_type_id",
        ),
    )
    op.create_index(op.f("ix_area_types_operator_id"), "area_types", ["operator_id"], unique=False)
    op.create_table(
        "zone_labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("zone", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            ZONE_CHECK,
            name=op.f("ck_zone_labels_zone_values"),
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["tenants.id"],
            name=op.f("fk_zone_labels_operator_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_zone_labels")),
        sa.UniqueConstraint("operator_id", "zone", name="uq_zone_labels_operator_id_zone"),
    )
    op.create_index(
        op.f("ix_zone_labels_operator_id"), "zone_labels", ["operator_id"], unique=False
    )
    op.add_column(
        "inspection_finding_items", sa.Column("zone", sa.String(length=40), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_inspection_finding_items_zone_values"), "inspection_finding_items", ZONE_CHECK
    )
    op.add_column(
        "inspection_findings",
        sa.Column(
            "activity_zones", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("inspection_findings", "activity_zones")
    op.drop_constraint(
        op.f("ck_inspection_finding_items_zone_values"), "inspection_finding_items", type_="check"
    )
    op.drop_column("inspection_finding_items", "zone")
    op.drop_index(op.f("ix_zone_labels_operator_id"), table_name="zone_labels")
    op.drop_table("zone_labels")
    op.drop_index(op.f("ix_area_types_operator_id"), table_name="area_types")
    op.drop_table("area_types")
