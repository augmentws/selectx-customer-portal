from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Credential, User
from tests.conftest import ADMIN_EMAIL, PASSWORD, USER_EMAIL, login


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_me_refresh_logout(client, users):
    tokens = login(client).json()

    me = client.get("/v1/auth/me", headers=_bearer(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == USER_EMAIL
    assert me.json()["is_admin"] is False

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


def test_logout_revokes_session(client, users):
    tokens = login(client).json()
    headers = _bearer(tokens["access_token"])

    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
    refresh = client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401


def test_login_rejects_bad_credentials(client, users):
    assert login(client, password="wrong").status_code == 401
    assert login(client, email="nobody@test.example").status_code == 401


def test_login_email_is_case_insensitive(client, users):
    assert login(client, email=ADMIN_EMAIL.upper()).status_code == 200


def test_access_token_cannot_be_used_as_refresh(client, users):
    tokens = login(client).json()
    resp = client.post("/v1/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


def test_me_rejects_missing_and_garbage_tokens(client):
    assert client.get("/v1/auth/me").status_code == 401
    assert client.get("/v1/auth/me", headers=_bearer("not-a-jwt")).status_code == 401


def test_password_stored_as_argon2id(users):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == USER_EMAIL))
        cred = db.get(Credential, user.id)
        assert cred.password_hash.startswith("$argon2id$")
        assert PASSWORD not in cred.password_hash
