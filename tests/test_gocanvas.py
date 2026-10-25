import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.models import GoCanvasRequest
from app.services.gocanvas import purge_raw_bodies
from tests.conftest import headers_for


def _stored(world) -> list[GoCanvasRequest]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(GoCanvasRequest)
                .where(GoCanvasRequest.id != world.gocanvas_request_a)
                .order_by(GoCanvasRequest.received_at)
            )
        )


def test_every_request_is_stored_as_received(client, world):
    resp = client.post(
        f"/v1/webhooks/gocanvas/{world.op_a}?form=42",
        content=b"<Submission><Form>42</Form></Submission>",
        headers={
            "Content-Type": "application/xml",
            "User-Agent": "GoCanvas-Webhook/1.0",
            "X-Forwarded-For": "203.0.113.9",
            "Authorization": "Bearer secret-token",
            "Cookie": "session=secret",
        },
    )
    assert resp.status_code == 200 and resp.json() == {"status": "accepted"}
    [stored] = _stored(world)
    assert (stored.method, stored.query_string, stored.content_type) == (
        "POST",
        "form=42",
        "application/xml",
    )
    assert stored.raw_body == "<Submission><Form>42</Form></Submission>"
    assert stored.body_size == 40
    assert stored.user_agent == "GoCanvas-Webhook/1.0"
    assert stored.forwarded_for == "203.0.113.9"
    assert stored.client_ip  # the test client's address
    # Credentials are never stored.
    assert "authorization" not in stored.headers and "cookie" not in stored.headers
    assert stored.headers["user-agent"] == "GoCanvas-Webhook/1.0"


def test_get_and_non_utf8_bodies_are_kept(client, world):
    assert client.get(f"/v1/webhooks/gocanvas/{world.op_a}?verify=1").status_code == 200
    client.put(f"/v1/webhooks/gocanvas/{world.op_a}", content=b"\xff\xfeok")
    get, put = _stored(world)
    assert (get.method, get.query_string, get.body_size) == ("GET", "verify=1", 0)
    assert (put.method, put.body_size) == ("PUT", 4) and put.raw_body.endswith("ok")


def test_unknown_operator_is_answered_the_same_but_not_stored(client, world):
    resp = client.post(f"/v1/webhooks/gocanvas/{uuid.uuid4()}", content=b"{}")
    assert resp.status_code == 200
    assert _stored(world) == []


def test_oversized_requests_are_refused(client, world, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "webhook_max_body_bytes", 10)
    resp = client.post(f"/v1/webhooks/gocanvas/{world.op_a}", content=b"x" * 11)
    assert resp.status_code == 413
    assert _stored(world) == []


def test_admins_list_and_read_requests(client, world):
    client.post(f"/v1/webhooks/gocanvas/{world.op_a}", content=b'{"a": 1}')
    admin = headers_for(client, world.emails["admin_a"])
    page = client.get(f"/v1/operators/{world.op_a}/gocanvas-requests", headers=admin).json()
    assert page["total"] == 2  # with the world's request
    newest = page["items"][0]
    assert "raw_body" not in newest and newest["has_raw_body"]
    detail = client.get(f"/v1/gocanvas-requests/{newest['id']}", headers=admin).json()
    assert detail["raw_body"] == '{"a": 1}'
    assert detail["headers"]["content-length"] == "8"


def test_raw_bodies_are_cleared_after_retention(client, world):
    client.post(f"/v1/webhooks/gocanvas/{world.op_a}", content=b"old")
    [old] = _stored(world)
    with SessionLocal() as db:
        db.execute(
            update(GoCanvasRequest)
            .where(GoCanvasRequest.id == old.id)
            .values(received_at=datetime.now(UTC) - timedelta(days=31))
        )
        db.commit()
        assert purge_raw_bodies(db) == 1
    [old] = _stored(world)
    assert old.raw_body is None and old.raw_body_purged_at is not None
