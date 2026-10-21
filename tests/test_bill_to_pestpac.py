import json

import responses
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import BillTo
from tests.conftest import (
    LOCATIONS_URL,
    PESTPAC_BASE,
    PESTPAC_TOKEN_URL,
    headers_for,
    locations_callback,
    pestpac_bill_to_body,
)

FINANCIAL = ("Balance", "InvoiceBalance", "CreditStatus", "899731", "Terms")
PERSONAL = ("TESTER", "PAT", "billing@acme-tacos.example", "A. REPRESENTATIVE")


def _onboard(client, headers, company_id, **body):
    return client.post(f"/v1/companies/{company_id}/bill-tos", json=body, headers=headers)


def _assert_identifying_only(text: str):
    for value in FINANCIAL + PERSONAL:
        assert value not in text, f"{value!r} leaked into the response"


def test_lookup_previews_without_storing(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    resp = client.get(
        f"/v1/companies/{world.company_a}/bill-tos/lookup",
        params={"pestpac_bill_to_id": 180020},
        headers=admin,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_name"] == "ACME TACOS · 100 EXAMPLE AVE, NEW YORK"
    assert body["details"] == {
        "pestpac_bill_to_id": 180020,
        "pestpac_bill_to_code": "491257",
        "pestpac_company": "ACME TACOS",
        "address": "100 EXAMPLE AVE",
        "address2": "FRONT 1",
        "city": "NEW YORK",
        "state": "NY",
        "zip": "10017",
        "phone": "555-010-0100",
        "pestpac_type": "ENTERPRISE",
    }
    assert body["onboarded_bill_to_id"] is None
    _assert_identifying_only(resp.text)
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(BillTo).where(BillTo.pestpac_bill_to_id == 180020)
            )
            == 0
        )


def test_lookup_flags_already_onboarded(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    body = client.get(
        f"/v1/companies/{world.company_a}/bill-tos/lookup",
        params={"pestpac_bill_to_id": 175101},
        headers=admin,
    ).json()
    assert body["onboarded_bill_to_id"] == str(world.bill_to_a)
    assert body["onboarded_company_id"] == str(world.company_a)


def test_lookup_unknown_bill_to(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    resp = client.get(
        f"/v1/companies/{world.company_a}/bill-tos/lookup",
        params={"pestpac_bill_to_id": 424242},
        headers=admin,
    )
    assert resp.status_code == 422


def test_onboard_stores_identifying_details_and_default_name(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    resp = _onboard(client, admin, world.company_a, pestpac_bill_to_id=180020)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "ACME TACOS · 100 EXAMPLE AVE, NEW YORK"
    assert body["pestpac_bill_to_code"] == "491257"
    assert body["phone"] == "555-010-0100"
    assert body["pestpac_type"] == "ENTERPRISE"
    assert body["zip"] == "10017"
    assert body["pestpac_fetched_at"] is not None
    _assert_identifying_only(resp.text)


def test_onboard_keeps_explicit_name(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    resp = _onboard(client, admin, world.company_a, pestpac_bill_to_id=180020, name="NYC flagship")
    assert resp.json()["name"] == "NYC flagship"
    assert resp.json()["pestpac_company"] == "ACME TACOS"


def test_refresh_updates_details_but_not_our_labels(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    client.patch(
        f"/v1/bill-tos/{world.bill_to_a}", json={"description": "HQ billing"}, headers=admin
    )
    changed = pestpac_bill_to_body(175101, Address="200 NEW ST", Phone="555-010-0199")
    with responses.RequestsMock() as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
        rsps.get(f"{PESTPAC_BASE}/BillTos/175101", body=json.dumps(changed))
        rsps.add_callback(responses.GET, LOCATIONS_URL, locations_callback())
        resp = client.post(f"/v1/bill-tos/{world.bill_to_a}/refresh", headers=admin)
    assert resp.status_code == 200
    body = resp.json()
    assert body["address"] == "200 NEW ST"
    assert body["phone"] == "555-010-0199"
    assert body["name"] == "Acme HQ"
    assert body["description"] == "HQ billing"
    assert body["pestpac_fetched_at"] is not None


def test_refresh_missing_in_pestpac_keeps_stored_data(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    client.post(f"/v1/bill-tos/{world.bill_to_a}/refresh", headers=admin)  # populate
    # The operator's cached client reuses its token, so the token call may not happen.
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
        rsps.get(f"{PESTPAC_BASE}/BillTos/175101", status=404)
        resp = client.post(f"/v1/bill-tos/{world.bill_to_a}/refresh", headers=admin)
    assert resp.status_code == 422
    stored = client.get(f"/v1/bill-tos/{world.bill_to_a}", headers=admin).json()
    assert stored["pestpac_company"] == "ACME TACOS"


def test_mismatched_bill_to_id_is_rejected(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    with responses.RequestsMock() as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
        rsps.get(f"{PESTPAC_BASE}/BillTos/180020", body=json.dumps(pestpac_bill_to_body(999)))
        resp = _onboard(client, admin, world.company_a, pestpac_bill_to_id=180020)
    assert resp.status_code == 502
