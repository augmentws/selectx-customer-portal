import uuid

import pytest

from app.models import Role
from app.models.rbac import Permission
from app.security.access import AccessScope
from app.security.permissions import RoleScope
from app.services.members import EscalationError, _check_no_escalation
from tests.conftest import PASSWORD, headers_for, login

TEMP = "temporary-password-1"


def _add(client, headers, tenant_id, **body):
    return client.post(f"/v1/tenants/{tenant_id}/members", json=body, headers=headers)


def test_new_member_must_change_temporary_password(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    created = _add(
        client,
        admin,
        world.op_a,
        email="New.Person@Test.example",
        role="operator_staff",
        temporary_password=TEMP,
    )
    assert created.status_code == 201
    assert created.json()["user_created"] is True
    assert created.json()["email"] == "new.person@test.example"
    assert created.json()["must_change_password"] is True

    first = login(client, "new.person@test.example", TEMP).json()
    second = login(client, "new.person@test.example", TEMP).json()
    h = {"Authorization": f"Bearer {first['access_token']}"}

    blocked = client.get("/v1/operators", headers=h)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Password change required"
    assert client.get("/v1/auth/me", headers=h).json()["must_change_password"] is True

    wrong = client.post(
        "/v1/auth/password",
        json={"current_password": "nope", "new_password": "a-brand-new-password"},
        headers=h,
    )
    assert wrong.status_code == 400
    same = client.post(
        "/v1/auth/password", json={"current_password": TEMP, "new_password": TEMP}, headers=h
    )
    assert same.status_code == 400
    short = client.post(
        "/v1/auth/password", json={"current_password": TEMP, "new_password": "short"}, headers=h
    )
    assert short.status_code == 422

    changed = client.post(
        "/v1/auth/password",
        json={"current_password": TEMP, "new_password": "a-brand-new-password"},
        headers=h,
    )
    assert changed.status_code == 204
    assert client.get("/v1/operators", headers=h).status_code == 200
    # Other sessions are signed out by a password change.
    other = {"Authorization": f"Bearer {second['access_token']}"}
    assert client.get("/v1/auth/me", headers=other).status_code == 401
    assert login(client, "new.person@test.example", TEMP).status_code == 401


def test_existing_user_joins_another_operator_without_password(client, world):
    pa = headers_for(client, world.emails["platform_admin"])
    resp = _add(client, pa, world.op_b, email=world.emails["staff_a"], role="operator_staff")
    assert resp.status_code == 201
    assert resp.json()["user_created"] is False
    staff = headers_for(client, world.emails["staff_a"])
    names = sorted(o["name"] for o in client.get("/v1/operators", headers=staff).json())
    assert names == ["Operator A", "Operator B"]


def test_new_user_requires_temporary_password(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    resp = _add(client, admin, world.op_a, email="nopw@test.example", role="operator_staff")
    assert resp.status_code == 422


def test_duplicate_membership_conflicts(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    resp = _add(client, admin, world.op_a, email=world.emails["staff_a"], role="operator_admin")
    assert resp.status_code == 409


@pytest.mark.parametrize(
    ("tenant", "role"),
    [("op_a", "platform_admin"), ("platform_id", "operator_admin"), ("op_a", "no_such_role")],
)
def test_role_must_fit_tenant_kind(client, world, tenant, role):
    pa = headers_for(client, world.emails["platform_admin"])
    resp = _add(
        client,
        pa,
        getattr(world, tenant),
        email="someone@test.example",
        role=role,
        temporary_password=TEMP,
    )
    assert resp.status_code == 422


def test_last_platform_admin_cannot_be_removed(client, world):
    pa = headers_for(client, world.emails["platform_admin"])
    me = world.user_ids["platform_admin"]
    resp = client.delete(f"/v1/tenants/{world.platform_id}/members/{me}", headers=pa)
    assert resp.status_code == 409

    second = _add(
        client,
        pa,
        world.platform_id,
        email="second.admin@test.example",
        role="platform_admin",
        temporary_password=TEMP,
    )
    assert second.status_code == 201
    resp = client.delete(f"/v1/tenants/{world.platform_id}/members/{me}", headers=pa)
    assert resp.status_code == 204


def test_member_list_shows_roles(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    members = client.get(f"/v1/tenants/{world.op_a}/members", headers=admin).json()
    assert {(m["email"], m["role"]) for m in members} == {
        (world.emails["admin_a"], "operator_admin"),
        (world.emails["staff_a"], "operator_staff"),
    }


def test_removed_member_loses_access_immediately(client, world):
    staff = headers_for(client, world.emails["staff_a"])
    admin = headers_for(client, world.emails["admin_a"])
    assert client.get(f"/v1/operators/{world.op_a}", headers=staff).status_code == 200
    client.delete(f"/v1/tenants/{world.op_a}/members/{world.user_ids['staff_a']}", headers=admin)
    # Same access token, permissions are re-read per request.
    assert client.get(f"/v1/operators/{world.op_a}", headers=staff).status_code == 404


def test_escalation_check_blocks_permissions_actor_lacks():
    """System roles can't trigger this yet; it protects custom roles when they arrive."""
    tenant_id = uuid.uuid4()
    scope = AccessScope(
        user_id=uuid.uuid4(),
        platform_id=uuid.uuid4(),
        operator_perms={tenant_id: frozenset({"companies:read", "members:write"})},
    )
    role = Role(
        name="custom",
        description="",
        scope=RoleScope.operator,
        permissions=[Permission(code="companies:write", description="")],
    )
    with pytest.raises(EscalationError):
        _check_no_escalation(scope.permissions_on(tenant_id), role)


def test_password_is_not_returned(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    resp = _add(
        client,
        admin,
        world.op_a,
        email="x@test.example",
        role="operator_staff",
        temporary_password=TEMP,
    )
    assert TEMP not in resp.text and PASSWORD not in resp.text


def _add_to_company(client, headers, company_id, **body):
    return client.post(f"/v1/companies/{company_id}/members", json=body, headers=headers)


def test_company_user_sees_only_their_company_dashboard(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    created = _add_to_company(
        client,
        admin,
        world.company_a,
        email="Store.Manager@Acme.example",
        role="company_manager",
        temporary_password=TEMP,
    )
    assert created.status_code == 201
    assert created.json()["user_created"] is True
    assert created.json()["company_id"] == str(world.company_a)
    assert created.json()["must_change_password"] is True

    token = login(client, "store.manager@acme.example", TEMP).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    changed = client.post(
        "/v1/auth/password",
        json={"current_password": TEMP, "new_password": "a-brand-new-password"},
        headers=h,
    )
    assert changed.status_code == 204
    h = headers_for(client, "store.manager@acme.example", "a-brand-new-password")

    me = client.get("/v1/auth/me", headers=h).json()
    assert me["memberships"] == []
    assert me["company_memberships"] == [
        {
            "company_id": str(world.company_a),
            "company_name": "Acme Restaurants",
            "operator_id": str(world.op_a),
            "role": "company_manager",
            "permissions": ["companies:read", "dashboards:read"],
        }
    ]
    assert client.get(f"/v1/companies/{world.company_a}/dashboard", headers=h).status_code == 200
    assert client.get(f"/v1/companies/{world.company_a}", headers=h).status_code == 200
    # Nothing beneath the company, and no other company.
    assert client.get(f"/v1/companies/{world.company_a}/bill-tos", headers=h).status_code == 404
    assert client.get(f"/v1/bill-tos/{world.bill_to_a}", headers=h).status_code == 404
    assert client.get(f"/v1/locations/{world.location_a}", headers=h).status_code == 404
    assert client.get(f"/v1/companies/{world.company_b}/dashboard", headers=h).status_code == 404
    assert client.get(f"/v1/operators/{world.op_a}", headers=h).status_code == 404


def test_company_member_list_shows_only_company_users(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    members = client.get(f"/v1/companies/{world.company_a}/members", headers=admin).json()
    assert [(m["email"], m["role"]) for m in members] == [
        (world.emails["manager_a"], "company_manager")
    ]
    assert client.get(f"/v1/companies/{world.company_b}/members", headers=admin).status_code == 404


@pytest.mark.parametrize(
    ("where", "role"),
    [("company", "operator_staff"), ("company", "platform_admin"), ("tenant", "company_manager")],
)
def test_company_roles_and_tenant_roles_do_not_mix(client, world, where, role):
    pa = headers_for(client, world.emails["platform_admin"])
    body = {"email": "someone@test.example", "role": role, "temporary_password": TEMP}
    if where == "company":
        resp = _add_to_company(client, pa, world.company_a, **body)
    else:
        resp = _add(client, pa, world.op_a, **body)
    assert resp.status_code == 422


def test_duplicate_company_membership_conflicts(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    resp = _add_to_company(
        client, admin, world.company_a, email=world.emails["manager_a"], role="company_manager"
    )
    assert resp.status_code == 409


def test_staff_user_can_also_be_a_company_user(client, world):
    """An existing user joins without a password; their operator access is unchanged."""
    admin = headers_for(client, world.emails["admin_a"])
    resp = _add_to_company(
        client, admin, world.company_a, email=world.emails["staff_a"], role="company_manager"
    )
    assert resp.status_code == 201
    assert resp.json()["user_created"] is False
    staff = headers_for(client, world.emails["staff_a"])
    assert client.get(f"/v1/companies/{world.company_a}/bill-tos", headers=staff).status_code == 200


def test_removed_company_user_loses_access_immediately(client, world):
    manager = headers_for(client, world.emails["manager_a"])
    admin = headers_for(client, world.emails["admin_a"])
    path = f"/v1/companies/{world.company_a}/dashboard"
    assert client.get(path, headers=manager).status_code == 200
    resp = client.delete(
        f"/v1/companies/{world.company_a}/members/{world.user_ids['manager_a']}", headers=admin
    )
    assert resp.status_code == 204
    assert client.get(path, headers=manager).status_code == 404


def test_deactivated_company_grants_nothing(client, world):
    manager = headers_for(client, world.emails["manager_a"])
    admin = headers_for(client, world.emails["admin_a"])
    resp = client.patch(
        f"/v1/companies/{world.company_a}", json={"is_active": False}, headers=admin
    )
    assert resp.status_code == 200
    assert (
        client.get(f"/v1/companies/{world.company_a}/dashboard", headers=manager).status_code == 404
    )
    assert client.get("/v1/auth/me", headers=manager).json()["company_memberships"] == []
