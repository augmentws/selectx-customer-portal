"""pestpac_connections; require pestpac_tenant_id on operators; connection permissions

Revision ID: a69218baf9ac
Revises: f446ad83e8c0
Create Date: 2026-10-21 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a69218baf9ac"
down_revision: str | Sequence[str] | None = "f446ad83e8c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Snapshot of app/security/permissions.py additions at this revision.
NEW_PERMISSIONS = {
    "pestpac_connection:read": "View PestPac API connection status",
    "pestpac_connection:write": "Set up and test PestPac API credentials",
}
GRANTED_TO = ("platform_admin", "operator_admin")

connection_status = postgresql.ENUM(
    "unverified", "verified", "failed", name="pestpac_connection_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()

    missing = (
        bind.execute(
            sa.text(
                "SELECT slug FROM tenants WHERE kind = 'operator' AND pestpac_tenant_id IS NULL"
            )
        )
        .scalars()
        .all()
    )
    if missing:
        raise RuntimeError(
            "Operators without a PestPac tenant ID must be fixed before this migration: "
            + ", ".join(missing)
        )
    op.create_check_constraint(
        op.f("ck_tenants_operator_has_pestpac"),
        "tenants",
        "kind = 'platform' OR pestpac_tenant_id IS NOT NULL",
    )

    connection_status.create(bind, checkfirst=True)
    op.create_table(
        "pestpac_connections",
        sa.Column("operator_id", sa.Uuid(), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("client_secret_enc", sa.Text(), nullable=False),
        sa.Column("password_enc", sa.Text(), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("api_key_last4", sa.String(length=4), nullable=False),
        sa.Column("status", connection_status, nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("pestpac_company_id", sa.Integer(), nullable=True),
        sa.Column("pestpac_company_name", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["operator_id"],
            ["tenants.id"],
            name=op.f("fk_pestpac_connections_operator_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name=op.f("fk_pestpac_connections_updated_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("operator_id", name=op.f("pk_pestpac_connections")),
    )

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
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"),
        {"codes": list(NEW_PERMISSIONS)},
    )  # role_permissions rows cascade
    op.drop_table("pestpac_connections")
    connection_status.drop(bind, checkfirst=True)
    op.drop_constraint(op.f("ck_tenants_operator_has_pestpac"), "tenants", type_="check")
