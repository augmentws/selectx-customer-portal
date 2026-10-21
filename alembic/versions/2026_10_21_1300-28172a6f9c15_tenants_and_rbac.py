"""tenants and rbac; replace users.is_admin with platform_admin membership; drop items

Revision ID: 28172a6f9c15
Revises: 04a0ab18114b
Create Date: 2026-10-21 13:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "28172a6f9c15"
down_revision: str | Sequence[str] | None = "04a0ab18114b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Snapshot of app/security/permissions.py at this revision. Migrations must not import app code;
# app.services.rbac.sync_rbac reconciles later registry changes, and a test checks they match.
PERMISSIONS = {
    "operators:read": "View operators",
    "operators:write": "Create and edit operators",
    "companies:read": "View companies",
    "companies:write": "Create and edit companies",
    "bill_tos:read": "View bill-tos",
    "bill_tos:write": "Onboard and edit bill-tos",
    "members:read": "View members",
    "members:write": "Add, change, and remove members",
    "roles:read": "View roles and permissions",
}
ROLES = {
    "platform_admin": (
        "platform",
        "Full access to every operator, company, and bill-to",
        list(PERMISSIONS),
    ),
    "operator_admin": (
        "operator",
        "Manages one operator's companies, bill-tos, and members",
        [
            "operators:read",
            "companies:read",
            "companies:write",
            "bill_tos:read",
            "bill_tos:write",
            "members:read",
            "members:write",
            "roles:read",
        ],
    ),
    "operator_staff": (
        "operator",
        "Read-only access to one operator's companies and bill-tos",
        ["operators:read", "companies:read", "bill_tos:read"],
    ),
}

tenant_kind = postgresql.ENUM("platform", "operator", name="tenant_kind", create_type=False)
role_scope = postgresql.ENUM("platform", "operator", name="role_scope", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    tenant_kind.create(bind, checkfirst=True)
    role_scope.create(bind, checkfirst=True)

    permissions = op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_permissions")),
    )
    tenants = op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("kind", tenant_kind, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("pestpac_tenant_id", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'platform') = (parent_id IS NULL)", name=op.f("ck_tenants_root_is_platform")
        ),
        sa.CheckConstraint(
            "pestpac_tenant_id IS NULL OR kind = 'operator'",
            name=op.f("ck_tenants_pestpac_only_on_operator"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["tenants.id"],
            name=op.f("fk_tenants_parent_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("pestpac_tenant_id", name=op.f("uq_tenants_pestpac_tenant_id")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_index(op.f("ix_tenants_parent_id"), "tenants", ["parent_id"], unique=False)
    op.create_index(
        "uq_tenants_single_platform",
        "tenants",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'platform'"),
    )
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("scope", role_scope, nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_roles_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_id_name"),
    )
    op.create_index(
        "uq_roles_system_name",
        "roles",
        ["name"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )
    role_permissions = op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_code", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_code"],
            ["permissions.code"],
            name=op.f("fk_role_permissions_permission_code_permissions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_role_permissions_role_id_roles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_code", name=op.f("pk_role_permissions")),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name=op.f("fk_memberships_role_id_roles"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_memberships_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),
    )
    op.create_index(op.f("ix_memberships_tenant_id"), "memberships", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False)

    # Seed: permissions, system roles, and the platform root tenant.
    op.bulk_insert(permissions, [{"code": c, "description": d} for c, d in PERMISSIONS.items()])
    role_ids = {name: uuid.uuid4() for name in ROLES}
    op.bulk_insert(
        roles,
        [
            {
                "id": role_ids[name],
                "tenant_id": None,
                "name": name,
                "description": desc,
                "scope": scope,
            }
            for name, (scope, desc, _) in ROLES.items()
        ],
    )
    op.bulk_insert(
        role_permissions,
        [
            {"role_id": role_ids[name], "permission_code": code}
            for name, (_, _, codes) in ROLES.items()
            for code in codes
        ],
    )
    platform_id = uuid.uuid4()
    op.bulk_insert(
        tenants,
        [
            {
                "id": platform_id,
                "parent_id": None,
                "kind": "platform",
                "name": "SELECTX",
                "slug": "selectx",
                "pestpac_tenant_id": None,
                "is_active": True,
            }
        ],
    )

    # Existing admins become platform_admin members before is_admin goes away.
    bind.execute(
        sa.text(
            "INSERT INTO memberships (id, user_id, tenant_id, role_id) "
            "SELECT gen_random_uuid(), id, :tenant, :role FROM users WHERE is_admin"
        ),
        {"tenant": platform_id, "role": role_ids["platform_admin"]},
    )

    op.add_column(
        "credentials",
        sa.Column("must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.drop_column("users", "is_admin")

    op.drop_table("items")
    sa.Enum(name="item_status").drop(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()

    item_status = postgresql.ENUM("active", "archived", name="item_status", create_type=False)
    item_status.create(bind, checkfirst=True)
    op.create_table(
        "items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", item_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
    )

    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    bind.execute(
        sa.text(
            "UPDATE users SET is_admin = true WHERE id IN ("
            " SELECT m.user_id FROM memberships m"
            " JOIN roles r ON r.id = m.role_id"
            " JOIN tenants t ON t.id = m.tenant_id"
            " WHERE r.name = 'platform_admin' AND t.kind = 'platform')"
        )
    )
    op.alter_column("users", "is_admin", server_default=None)
    op.drop_column("credentials", "must_change_password")

    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_tenant_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("role_permissions")
    op.drop_index("uq_roles_system_name", table_name="roles")
    op.drop_table("roles")
    op.drop_index("uq_tenants_single_platform", table_name="tenants")
    op.drop_index(op.f("ix_tenants_parent_id"), table_name="tenants")
    op.drop_table("tenants")
    op.drop_table("permissions")
    role_scope.drop(bind, checkfirst=True)
    tenant_kind.drop(bind, checkfirst=True)
