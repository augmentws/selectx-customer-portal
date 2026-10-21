"""bill_tos: identifying details from PestPac

Revision ID: 84da16024a83
Revises: a69218baf9ac
Create Date: 2026-10-21 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "84da16024a83"
down_revision: str | Sequence[str] | None = "a69218baf9ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [
    ("pestpac_bill_to_code", sa.String(length=50)),
    ("pestpac_company", sa.String(length=200)),
    ("address", sa.String(length=200)),
    ("address2", sa.String(length=200)),
    ("city", sa.String(length=100)),
    ("state", sa.String(length=50)),
    ("zip", sa.String(length=20)),
    ("phone", sa.String(length=50)),
    ("pestpac_type", sa.String(length=100)),
    ("pestpac_fetched_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    # Nullable: bill-tos onboarded before this have no PestPac details until refreshed.
    for name, type_ in COLUMNS:
        op.add_column("bill_tos", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("bill_tos", name)
