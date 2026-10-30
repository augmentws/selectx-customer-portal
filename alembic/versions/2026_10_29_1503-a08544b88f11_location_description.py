"""location description

Revision ID: a08544b88f11
Revises: 00ba42dc033b
Create Date: 2026-10-29 15:03:35.993451

locations.description is our own text for a location (e.g. the customer's store name from the
Restaurant Leader Report). PestPac syncs never write it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a08544b88f11"
down_revision: str | Sequence[str] | None = "00ba42dc033b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("description", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("locations", "description")
