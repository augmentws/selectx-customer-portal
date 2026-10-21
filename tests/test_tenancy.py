import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models import BillTo, Tenant, TenantKind
from tests.conftest import headers_for


def test_operator_list_is_scoped(client, world):
    def names(actor):
        resp = client.get("/v1/operators", headers=headers_for(client, world.emails[actor]))
        return sorted(o["name"] for o in resp.json())

    assert names("platform_admin") == ["Operator A", "Operator B"]
    assert names("admin_a") == ["Operator A"]
    assert names("staff_a") == ["Operator A"]
    assert names("admin_b") == ["Operator B"]


def test_operator_slug_and_pestpac_tenant_are_unique(client, world):
    headers = headers_for(client, world.emails["platform_admin"])
    dup_slug = client.post("/v1/operators", json={"name": "X", "slug": "op-a"}, headers=headers)
    assert dup_slug.status_code == 409
    dup_pp = client.post(
        "/v1/operators",
        json={"name": "X", "slug": "op-x", "pestpac_tenant_id": "115060"},
        headers=headers,
    )
    assert dup_pp.status_code == 409
    move_pp = client.patch(
        f"/v1/operators/{world.op_b}", json={"pestpac_tenant_id": "115060"}, headers=headers
    )
    assert move_pp.status_code == 409


def test_operator_slug_format(client, world):
    headers = headers_for(client, world.emails["platform_admin"])
    resp = client.post("/v1/operators", json={"name": "X", "slug": "Bad Slug"}, headers=headers)
    assert resp.status_code == 422


def test_deactivated_operator_hides_from_its_members(client, world):
    pa = headers_for(client, world.emails["platform_admin"])
    admin_a = headers_for(client, world.emails["admin_a"])
    assert client.patch(
        f"/v1/operators/{world.op_a}", json={"is_active": False}, headers=pa
    ).is_success

    assert client.get(f"/v1/operators/{world.op_a}", headers=admin_a).status_code == 404
    assert client.get(f"/v1/operators/{world.op_a}", headers=pa).json()["is_active"] is False


def test_partial_update_rejects_explicit_null(client, world):
    headers = headers_for(client, world.emails["admin_a"])
    resp = client.patch(f"/v1/companies/{world.company_a}", json={"name": None}, headers=headers)
    assert resp.status_code == 422
    # Omitted fields are left alone.
    resp = client.patch(f"/v1/companies/{world.company_a}", json={}, headers=headers)
    assert resp.json()["name"] == "Acme Restaurants"


def test_bill_to_onboarding(client, world):
    headers = headers_for(client, world.emails["admin_a"])
    resp = client.post(
        f"/v1/companies/{world.company_a}/bill-tos",
        json={"pestpac_bill_to_id": 180020, "name": "Acme NE", "description": "Northeast region"},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["operator_id"] == str(world.op_a)
    assert body["onboarded_by"] == str(world.user_ids["admin_a"])
    assert body["description"] == "Northeast region"

    listed = client.get(f"/v1/companies/{world.company_a}/bill-tos", headers=headers).json()
    assert [b["pestpac_bill_to_id"] for b in listed] == [175101, 180020]


def test_bill_to_unique_within_operator(client, world):
    pa = headers_for(client, world.emails["platform_admin"])
    other_company = client.post(
        f"/v1/operators/{world.op_a}/companies", json={"name": "Other"}, headers=pa
    ).json()
    dup = client.post(
        f"/v1/companies/{other_company['id']}/bill-tos",
        json={"pestpac_bill_to_id": 175101, "name": "Dup"},
        headers=pa,
    )
    assert dup.status_code == 409
    assert "another company" in dup.json()["detail"]

    # The same PestPac id under a different operator is a different bill-to.
    other_op = client.post(
        f"/v1/companies/{world.company_b}/bill-tos",
        json={"pestpac_bill_to_id": 175101, "name": "B's 175101"},
        headers=pa,
    )
    assert other_op.status_code == 201


def test_bill_to_cannot_cross_operators_in_db(world):
    with SessionLocal() as db:
        db.add(
            BillTo(
                operator_id=world.op_b,
                company_id=world.company_a,
                pestpac_bill_to_id=999,
                name="Mismatched",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_only_one_platform_tenant(world):
    with SessionLocal() as db:
        db.add(Tenant(kind=TenantKind.platform, name="Second", slug="second"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_pestpac_tenant_only_on_operators(world):
    with SessionLocal() as db:
        platform = db.get(Tenant, world.platform_id)
        platform.pestpac_tenant_id = "1"
        with pytest.raises(IntegrityError):
            db.commit()
