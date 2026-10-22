from app.db.session import SessionLocal
from app.security.permissions import SYSTEM_ROLES, Perm
from app.services.rbac import sync_rbac


def test_migration_seed_matches_code_registry():
    """If this fails, a permission or system role changed in app/security/permissions.py
    without a migration that brings the database along."""
    with SessionLocal() as db:
        changes = sync_rbac(db)
        db.rollback()
    assert changes == []


def test_platform_admin_has_every_permission():
    _, _, perms = SYSTEM_ROLES["platform_admin"]
    assert perms == frozenset(Perm)


def test_me_lists_memberships_and_permissions(client, world):
    from tests.conftest import headers_for

    me = client.get("/v1/auth/me", headers=headers_for(client, world.emails["staff_a"])).json()
    assert me["must_change_password"] is False
    assert me["memberships"] == [
        {
            "tenant_id": str(world.op_a),
            "tenant_name": "Operator A",
            "tenant_kind": "operator",
            "role": "operator_staff",
            "permissions": [
                "bill_tos:read",
                "companies:read",
                "dashboards:read",
                "operators:read",
                "reports:read",
            ],
        }
    ]
