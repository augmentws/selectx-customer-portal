import re
import uuid
from datetime import timedelta

import jwt
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Credential, User
from app.security.tokens import create_token
from tests.conftest import PASSWORD, login


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_me_refresh_logout(client, world):
    email = world.emails["staff_a"]
    tokens = login(client, email).json()

    me = client.get("/v1/auth/me", headers=_bearer(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == email

    rotated = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert rotated.status_code == 200
    new = rotated.json()
    assert new["refresh_token"] != tokens["refresh_token"]

    # The rotated-out refresh token is rejected...
    replay = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    # ...and reuse revokes the whole family, including the newest tokens.
    assert client.get("/v1/auth/me", headers=_bearer(new["access_token"])).status_code == 401
    assert (
        client.post("/v1/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code
        == 401
    )


def test_logout_revokes_session(client, world):
    tokens = login(client, world.emails["staff_a"]).json()
    headers = _bearer(tokens["access_token"])

    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
    refresh = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401


def test_login_rejects_bad_credentials(client, world):
    assert login(client, world.emails["staff_a"], password="wrong").status_code == 401
    assert login(client, "nobody@test.example").status_code == 401


def test_login_email_is_case_insensitive(client, world):
    assert login(client, world.emails["platform_admin"].upper()).status_code == 200


def test_access_token_cannot_be_used_as_refresh(client, world):
    tokens = login(client, world.emails["staff_a"]).json()
    resp = client.post("/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


def test_me_rejects_missing_and_garbage_tokens(client):
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers=_bearer("not-a-jwt")).status_code == 401


def test_password_stored_as_argon2id(world):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == world.emails["staff_a"]))
        cred = db.get(Credential, user.id)
        assert cred.password_hash.startswith("$argon2id$")
        assert PASSWORD not in cred.password_hash


# Public by design: they issue or check tokens themselves, or callers hold no session.
PUBLIC_ROUTES = {
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/refresh"),
    ("POST", "/v1/webhooks/pestpac"),
    ("POST", "/v1/webhooks/gocanvas/{operator_id}"),
}


def test_every_other_route_refuses_a_request_without_a_token(client, world):
    """The access matrix only tries signed-in users; this catches a route that forgot the token
    check altogether."""
    from app.main import app

    routes = [
        (method.upper(), path)
        for path, ops in app.openapi()["paths"].items()
        if path.startswith("/v1/")
        for method in ops
    ]
    assert len(routes) > 60  # the schema was read
    accepted = []
    for method, path in routes:
        if (method, path) in PUBLIC_ROUTES:
            continue
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        resp = client.request(method, url, json={})
        if resp.status_code != 401:
            accepted.append((method, path, resp.status_code))
    assert not accepted, f"answered without a token: {accepted}"


def _claims(access_token: str) -> dict:
    return jwt.decode(access_token, options={"verify_signature": False})


def test_expired_access_token_is_refused(client, world):
    claims = _claims(login(client, world.emails["staff_a"]).json()["access_token"])
    expired = create_token(
        subject=uuid.UUID(claims["sub"]),
        token_type="access",
        ttl=timedelta(seconds=-1),
        extra={"sid": claims["sid"]},  # a live session: only the expiry is wrong
    )
    assert client.get("/v1/auth/me", headers=_bearer(expired)).status_code == 401


def test_refresh_token_and_forged_tokens_are_refused_as_bearer(client, world):
    tokens = login(client, world.emails["staff_a"]).json()
    assert client.get("/v1/auth/me", headers=_bearer(tokens["refresh_token"])).status_code == 401
    forged = jwt.encode(_claims(tokens["access_token"]), "not-our-secret", algorithm="HS256")
    assert client.get("/v1/auth/me", headers=_bearer(forged)).status_code == 401
    unsigned = jwt.encode(_claims(tokens["access_token"]), None, algorithm="none")
    assert client.get("/v1/auth/me", headers=_bearer(unsigned)).status_code == 401
