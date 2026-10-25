from datetime import UTC, datetime, timedelta

import pytest

from app.db.session import SessionLocal
from app.models import WebhookEntity, WebhookEvent
from tests.conftest import headers_for


def _event(world, n: int, *, operator=None, **fields) -> WebhookEvent:
    defaults = {
        "entity": WebhookEntity.location,
        "action": "update",
        "pestpac_entity_id": 800001,
        "pestpac_location_id": 800001,
        "signature_status": "valid",
        "body_sha256": f"{n:064d}",
        "raw_body": "{}",
        # The world's event is received "now"; these are older, one hour apart.
        "received_at": datetime.now(UTC) - timedelta(hours=n),
    }
    return WebhookEvent(operator_id=operator or world.op_a, **(defaults | fields))


@pytest.fixture
def events(world):
    with SessionLocal() as db:
        db.add_all(
            [
                _event(
                    world, 1, entity=WebhookEntity.note, action="create", pestpac_entity_id=3073391
                ),
                _event(world, 2, signature_status="invalid"),
                _event(world, 3, status="failed", error="boom"),
                _event(world, 4, operator=world.op_b),
            ]
        )
        db.commit()


def _list(client, world, actor="admin_a", **params):
    resp = client.get(
        f"/v1/operators/{world.op_a}/webhook-events",
        params=params,
        headers=headers_for(client, world.emails[actor]),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_lists_own_operator_newest_first_without_bodies(client, world, events):
    page = _list(client, world)
    assert page["total"] == 4  # the world's event plus three; operator B's is not listed
    items = page["items"]
    assert items[0]["id"] == str(world.webhook_event_a)
    assert [i["entity"] for i in items[1:]] == ["note", "location", "location"]
    assert all("raw_body" not in i and i["has_raw_body"] for i in items)


@pytest.mark.parametrize(
    ("params", "total"),
    [
        ({"entity": "note"}, 1),
        ({"action": "Create"}, 1),
        ({"status": "failed"}, 1),
        ({"signature_status": "invalid"}, 1),
        ({"entity": "location", "status": "received"}, 1),
        ({"entity_id": 3073391}, 1),
        ({"entity_id": 3073391, "entity": "location"}, 0),
    ],
)
def test_filters(client, world, events, params, total):
    assert _list(client, world, **params)["total"] == total


def test_paging(client, world, events):
    page = _list(client, world, limit=2, offset=2)
    assert (page["total"], page["limit"], page["offset"]) == (4, 2, 2)
    assert [i["signature_status"] for i in page["items"]] == ["invalid", "valid"]


def test_unknown_filter_value_is_422(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    resp = client.get(
        f"/v1/operators/{world.op_a}/webhook-events", params={"entity": "x"}, headers=admin
    )
    assert resp.status_code == 422


def test_detail_has_body_and_links_our_records(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    body = client.get(f"/v1/webhook-events/{world.webhook_event_a}", headers=admin).json()
    assert body["raw_body"] == '{"EntityType": "Service Order"}'
    assert body["has_raw_body"] is True
    assert body["location_id"] == str(world.location_a)
    assert body["bill_to_id"] == str(world.bill_to_a)


def test_detail_after_body_is_cleared(client, world):
    purged_at = datetime.now(UTC)
    with SessionLocal() as db:
        event = _event(world, 9, raw_body=None, raw_body_purged_at=purged_at)
        db.add(event)
        db.commit()
        event_id = event.id
    admin = headers_for(client, world.emails["admin_a"])
    body = client.get(f"/v1/webhook-events/{event_id}", headers=admin).json()
    assert body["raw_body"] is None and body["has_raw_body"] is False
    assert body["raw_body_purged_at"] is not None
