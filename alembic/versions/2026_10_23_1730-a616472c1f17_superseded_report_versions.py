"""superseded report versions

Revision ID: a616472c1f17
Revises: d7b4178c418b
Create Date: 2026-10-23 17:30:09.461838

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a616472c1f17"
down_revision: str | Sequence[str] | None = "d7b4178c418b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Only an order's newest version is final; earlier finals become superseded.
    op.execute("ALTER TYPE report_status ADD VALUE IF NOT EXISTS 'superseded'")


def downgrade() -> None:
    """Downgrade schema."""
    # ADD VALUE can't be undone in place: superseded versions go back to final, and the type
    # is recreated without the value.
    op.execute("UPDATE reports SET status = 'final' WHERE status = 'superseded'")
    op.execute("ALTER TYPE report_status RENAME TO report_status_old")
    op.execute("CREATE TYPE report_status AS ENUM ('draft', 'drafting', 'final')")
    op.execute(
        "ALTER TABLE reports ALTER COLUMN status TYPE report_status "
        "USING status::text::report_status"
    )
    op.execute("DROP TYPE report_status_old")
