import logging

import requests
import responses
from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.models import PestPacConnection
from app.security.secrets import decrypt
from tests.conftest import PESTPAC_BASE, PESTPAC_TOKEN_URL, headers_for

SECRETS = {
    "client_secret": "s3cret-client",
    "password": "s3cret-pass",
    "api_key": "s3cret-key-9876",
}
FULL = {"client_id": "client-b", "username": "api-user-b", **SECRETS}


def _url(world, suffix=""):
    return f"/v1/operators/{world.op_b}/pestpac-connection{suffix}"


def test_unconfigured_connection(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    body = client.get(_url(world), headers=admin_b).json()
    assert body["configured"] is False
    assert body["pestpac_tenant_id"] == "220000"


def test_first_setup_requires_all_secrets(client, world, pestpac):
    admin_b = headers_for(client, world.emails["admin_b"])
    resp = client.put(
        _url(world), json={"client_id": "c", "username": "u", "password": "p"}, headers=admin_b
    )
    assert resp.status_code == 422
    assert "client_secret" in resp.json()["detail"] and "api_key" in resp.json()["detail"]


def test_setup_verifies_and_never_returns_secrets(client, world, pestpac):
    admin_b = headers_for(client, world.emails["admin_b"])
    resp = client.put(_url(world), json=FULL, headers=admin_b)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "verified"
    assert body["pestpac_company_name"] == "Select Exterminating"
    assert body["pestpac_company_id"] == 1
    assert body["api_key_last4"] == "9876"
    assert body["has_client_secret"] and body["has_password"]
    for secret in SECRETS.values():
        assert secret not in resp.text
        assert secret not in client.get(_url(world), headers=admin_b).text

    # The verification call carried this operator's API key and tenant ID.
    company_setup = [c for c in pestpac.calls if c.request.url.endswith("/CompanySetup")][-1]
    assert company_setup.request.headers["apiKey"] == "s3cret-key-9876"
    assert company_setup.request.headers["tenant-id"] == "220000"
    assert company_setup.request.headers["Authorization"] == "Bearer test-token"


def test_secrets_are_encrypted_at_rest(client, world, pestpac):
    admin_b = headers_for(client, world.emails["admin_b"])
    client.put(_url(world), json=FULL, headers=admin_b)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT client_secret_enc, password_enc, api_key_enc FROM pestpac_connections "
                "WHERE operator_id = :id"
            ),
            {"id": world.op_b},
        ).one()
    for stored, plain in zip(row, SECRETS.values(), strict=True):
        assert plain not in stored
        assert decrypt(stored) == plain


def test_omitted_secrets_are_kept(client, world, pestpac):
    admin_b = headers_for(client, world.emails["admin_b"])
    client.put(_url(world), json=FULL, headers=admin_b)
    resp = client.put(
        _url(world), json={"client_id": "client-b2", "username": "api-user-b"}, headers=admin_b
    )
    assert resp.json()["client_id"] == "client-b2"
    assert resp.json()["status"] == "verified"
    with SessionLocal() as db:
        conn = db.get(PestPacConnection, world.op_b)
        assert decrypt(conn.api_key_enc) == SECRETS["api_key"]


def test_rejected_credentials_mark_failed(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    with responses.RequestsMock() as rsps:
        rsps.post(PESTPAC_TOKEN_URL, status=400, json={"error": "invalid_grant"})
        body = client.put(_url(world), json=FULL, headers=admin_b).json()
    assert body["status"] == "failed"
    assert "rejected the credentials" in body["last_error"]
    assert "invalid_grant" not in body["last_error"]


def test_rejected_api_key_marks_failed(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    with responses.RequestsMock() as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
        # 401 triggers one token refresh and retry; both attempts are refused.
        rsps.get(f"{PESTPAC_BASE}/CompanySetup", status=401)
        body = client.put(_url(world), json=FULL, headers=admin_b).json()
    assert body["status"] == "failed"
    assert "API key and tenant ID" in body["last_error"]


def test_unreachable_pestpac_marks_failed(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    with responses.RequestsMock() as rsps:
        rsps.post(PESTPAC_TOKEN_URL, body=requests.ConnectTimeout("timed out"))
        body = client.put(_url(world), json=FULL, headers=admin_b).json()
    assert body["status"] == "failed"
    assert "Could not reach" in body["last_error"]


def test_verify_requires_setup(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    assert client.post(_url(world, "/verify"), headers=admin_b).status_code == 404


def test_changing_pestpac_tenant_resets_connection(client, world, pestpac):
    pa = headers_for(client, world.emails["platform_admin"])
    resp = client.patch(
        f"/v1/operators/{world.op_a}", json={"pestpac_tenant_id": "115061"}, headers=pa
    )
    assert resp.status_code == 200
    conn = client.get(f"/v1/operators/{world.op_a}/pestpac-connection", headers=pa).json()
    assert conn["status"] == "unverified"
    assert conn["pestpac_company_name"] is None


def test_onboarding_blocked_until_connection_verified(client, world, pestpac):
    admin_b = headers_for(client, world.emails["admin_b"])
    payload = {"pestpac_bill_to_id": 175101, "name": "Beta HQ"}
    blocked = client.post(
        f"/v1/companies/{world.company_b}/bill-tos", json=payload, headers=admin_b
    )
    assert blocked.status_code == 409
    assert "PestPac API access" in blocked.json()["detail"]

    client.put(_url(world), json=FULL, headers=admin_b)
    allowed = client.post(
        f"/v1/companies/{world.company_b}/bill-tos", json=payload, headers=admin_b
    )
    assert allowed.status_code == 201


def test_onboarding_rejects_unknown_bill_to(client, world, pestpac):
    admin_a = headers_for(client, world.emails["admin_a"])
    resp = client.post(
        f"/v1/companies/{world.company_a}/bill-tos",
        json={"pestpac_bill_to_id": 424242, "name": "Nope"},
        headers=admin_a,
    )
    assert resp.status_code == 422
    assert "not found in PestPac" in resp.json()["detail"]


def test_onboarding_reports_pestpac_outage(client, world):
    admin_a = headers_for(client, world.emails["admin_a"])
    with responses.RequestsMock() as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
        rsps.get(f"{PESTPAC_BASE}/BillTos/180020", status=503)
        resp = client.post(
            f"/v1/companies/{world.company_a}/bill-tos",
            json={"pestpac_bill_to_id": 180020, "name": "NE"},
            headers=admin_a,
        )
    assert resp.status_code == 502


def test_bodies_not_logged_by_default(client, world, pestpac, caplog):
    admin_b = headers_for(client, world.emails["admin_b"])
    with caplog.at_level(logging.INFO, logger="app.integrations.pestpac.client"):
        client.put(_url(world), json=FULL, headers=admin_b)
    assert "Select Exterminating" not in caplog.text
    assert "GET" in caplog.text  # the request line itself is still logged
    for secret in SECRETS.values():
        assert secret not in caplog.text


def test_bodies_logged_only_with_debug_flag(client, world, pestpac, caplog, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("PESTPAC_DEBUG_BODIES", "true")
    get_settings.cache_clear()
    try:
        admin_b = headers_for(client, world.emails["admin_b"])
        with caplog.at_level(logging.INFO, logger="app.integrations.pestpac.client"):
            client.put(_url(world), json=FULL, headers=admin_b)
    finally:
        get_settings.cache_clear()
    assert "Select Exterminating" in caplog.text
