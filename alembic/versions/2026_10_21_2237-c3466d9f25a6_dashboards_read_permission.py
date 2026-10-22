"""dashboards:read permission for every system role

Revision ID: c3466d9f25a6
Revises: 3c45ad5e5cad
Create Date: 2026-10-21 22:37:28.274737

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3466d9f25a6"
down_revision: str | Sequence[str] | None = "3c45ad5e5cad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Snapshot of app/security/permissions.py additions at this revision.
NEW_PERMISSIONS = {"dashboards:read": "View program dashboards"}
GRANTED_TO = ("platform_admin", "operator_admin", "operator_staff")


def upgrade() -> None:
    bind = op.get_bind()
    for code, description in NEW_PERMISSIONS.items():
        bind.execute(
            sa.text("INSERT INTO permissions (code, description) VALUES (:code, :description)"),
            {"code": code, "description": description},
        )
    bind.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_code) "
            "SELECT r.id, p.code FROM roles r CROSS JOIN permissions p "
            "WHERE r.tenant_id IS NULL AND r.name = ANY(:roles) AND p.code = ANY(:codes)"
        ),
        {"roles": list(GRANTED_TO), "codes": list(NEW_PERMISSIONS)},
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"),
        {"codes": list(NEW_PERMISSIONS)},
    )  # role_permissions rows cascade
