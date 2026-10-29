import logging

import pytest
import requests
import responses
from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.integrations.gocanvas import GoCanvasClient
from app.models import ConnectionStatus, GoCanvasConnection, Tenant
from app.security.secrets import decrypt
from app.services.gocanvas_connection import ConnectionNotReadyError, get_gocanvas_client
from tests.conftest import GOCANVAS_BASE, GOCANVAS_TOKEN_URL, headers_for

SECRET = "s3cret-gocanvas-client"
FULL = {"client_id": "gocanvas-client-b", "client_secret": SECRET}


def _url(world, suffix=""):
    return f"/v1/operators/{world.op_b}/gocanvas-connection{suffix}"


def _multipart_fields(body: bytes) -> dict[str, str]:
    """The plain fields of a multipart/form-data body."""
    fields = {}
    for part in body.split(b"--")[1:]:
        if b'name="' not in part:
            continue
        name = part.split(b'name="', 1)[1].split(b'"', 1)[0].decode()
        fields[name] = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0].decode()
    return fields


def test_unconfigured_connection(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    body = client.get(_url(world), headers=admin_b).json()
    assert body["configured"] is False
    assert body["has_client_secret"] is False


def test_first_setup_requires_the_secret(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    resp = client.put(_url(world), json={"client_id": "c"}, headers=admin_b)
    assert resp.status_code == 422
    assert "client_secret" in resp.json()["detail"]


def test_setup_verifies_with_client_credentials_and_never_returns_the_secret(
    client, world, pestpac
):
    admin_b = headers_for(client, world.emails["admin_b"])
    resp = client.put(_url(world), json=FULL, headers=admin_b)
    assert resp.status_code == 200
    body = resp.json()
    assert (body["status"], body["client_id"], body["has_client_secret"]) == (
        "verified",
        "gocanvas-client-b",
        True,
    )
    assert SECRET not in resp.text
    assert SECRET not in client.get(_url(world), headers=admin_b).text

    [token_call] = [c for c in pestpac.calls if c.request.url == GOCANVAS_TOKEN_URL]
    assert token_call.request.headers["Content-Type"].startswith("multipart/form-data")
    assert _multipart_fields(token_call.request.body) == {
        "grant_type": "client_credentials",
        "client_id": "gocanvas-client-b",
        "client_secret": SECRET,
        "scope": "api",
    }


def test_secret_is_encrypted_at_rest_and_kept_when_omitted(client, world, pestpac):
    admin_b = headers_for(client, world.emails["admin_b"])
    client.put(_url(world), json=FULL, headers=admin_b)
    resp = client.put(_url(world), json={"client_id": "gocanvas-client-b2"}, headers=admin_b)
    assert (resp.json()["client_id"], resp.json()["status"]) == ("gocanvas-client-b2", "verified")
    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT client_secret_enc FROM gocanvas_connections WHERE operator_id = :id"),
            {"id": world.op_b},
        ).scalar_one()
    assert SECRET not in stored
    assert decrypt(stored) == SECRET


def test_rejected_credentials_mark_failed_without_echoing_the_body(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    with responses.RequestsMock() as rsps:
        rsps.post(GOCANVAS_TOKEN_URL, status=401, json={"error": "invalid_client"})
        body = client.put(_url(world), json=FULL, headers=admin_b).json()
    assert body["status"] == "failed"
    assert "rejected the credentials" in body["last_error"]
    assert "invalid_client" not in body["last_error"]


def test_unreachable_gocanvas_marks_failed(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    with responses.RequestsMock() as rsps:
        rsps.post(GOCANVAS_TOKEN_URL, body=requests.ConnectTimeout("timed out"))
        body = client.put(_url(world), json=FULL, headers=admin_b).json()
    assert body["status"] == "failed"
    assert "Could not reach" in body["last_error"]


def test_verify_requires_setup(client, world):
    admin_b = headers_for(client, world.emails["admin_b"])
    assert client.post(_url(world, "/verify"), headers=admin_b).status_code == 404


def test_client_needs_a_verified_connection(client, world):
    with SessionLocal() as db:
        with pytest.raises(ConnectionNotReadyError, match="verify GoCanvas API access"):
            get_gocanvas_client(db, db.get(Tenant, world.op_b))
        operator_a = db.get(Tenant, world.op_a)
        client_a = get_gocanvas_client(db, operator_a)
        assert isinstance(client_a, GoCanvasClient)
        assert get_gocanvas_client(db, operator_a) is client_a  # cached

        db.get(GoCanvasConnection, world.op_a).status = ConnectionStatus.failed
        with pytest.raises(ConnectionNotReadyError):
            get_gocanvas_client(db, operator_a)


def test_client_reuses_the_token_and_refetches_once_on_401(caplog):
    client = GoCanvasClient("id", "secret", token_url=GOCANVAS_TOKEN_URL, base_url=GOCANVAS_BASE)
    submission_url = f"{GOCANVAS_BASE}/submissions/268565507"
    with responses.RequestsMock() as rsps:
        token = rsps.post(GOCANVAS_TOKEN_URL, json={"access_token": "t1", "expires_in": 7200})
        rsps.get(submission_url, json={"id": 268565507, "customer": "Store #9001"})
        with caplog.at_level(logging.INFO, logger="app.integrations.gocanvas.client"):
            assert client.get_submission(268565507).json()["id"] == 268565507
            assert client.get_submission(268565507).status_code == 200
        assert token.call_count == 1
        assert rsps.calls[1].request.headers["Authorization"] == "Bearer t1"
        # Response bodies are customer data: never logged.
        assert "Store #9001" not in caplog.text

        rsps.replace(responses.GET, submission_url, status=401)
        assert client.get_submission(268565507).status_code == 401
        assert token.call_count == 2
