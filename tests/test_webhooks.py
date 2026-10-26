import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app import worker
from app.db.session import SessionLocal
from app.models import (
    BillTo,
    Invoice,
    Note,
    PestPacConnection,
    ServiceOrder,
    SyncJob,
    WebhookEntity,
    WebhookEvent,
)
from app.security.secrets import encrypt
from app.services import webhook_handlers
from app.services.webhooks import purge_raw_bodies
from tests.conftest import ONBOARDED_BILL_TO, WORLD_WEBHOOK_SHA, pestpac_invoice, pestpac_order

URL = "/v1/webhooks/pestpac"
TENANT = "115060"  # operator A
SECRET = "webhook-secret-a"
TIMESTAMP = "2026-10-21T22:24:30Z"
STORE = 900001  # a location of the onboarded bill-to


def envelope(entity_type: str, entity_id: int, action: str, body: dict | None) -> dict:
    return {
        "TenantId": TENANT,
        "EntityType": entity_type,
        "EntityId": entity_id,
        "Action": action,
        "Url": f"https://api.workwave.com/pestpac/v1/x/{entity_id}",
        "EntityBody": body,
    }


def sign(body: dict | None, timestamp: str = TIMESTAMP, secret: str = SECRET) -> str:
    message = (json.dumps(body) + timestamp).encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest().upper()


def post(client, payload: dict, *, signature: str | None = None, timestamp: str = TIMESTAMP):
    headers = {"Content-Type": "application/json", "timestamputc": timestamp}
    if signature is not None:
        headers["signature"] = signature
    return client.post(URL, content=json.dumps(payload), headers=headers)


def events() -> list[WebhookEvent]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(WebhookEvent)
                .where(WebhookEvent.body_sha256 != WORLD_WEBHOOK_SHA)
                .order_by(WebhookEvent.received_at)
            )
        )


@pytest.fixture
def secret(world):
    with SessionLocal() as db:
        db.execute(
            update(PestPacConnection)
            .where(PestPacConnection.operator_id == world.op_a)
            .values(webhook_secret_enc=encrypt(SECRET))
        )
        db.commit()


def order_event(bill_to_id: int = ONBOARDED_BILL_TO, action: str = "Update") -> dict:
    return envelope("Service Order", 1552079, action, pestpac_order(1552079, STORE, bill_to_id))


def test_sender_ip_and_user_agent_are_recorded(client, onboarded):
    payload = order_event()
    headers = {
        "Content-Type": "application/json",
        "timestamputc": TIMESTAMP,
        "User-Agent": "PestPac-Webhooks/2",
        "X-Forwarded-For": "198.51.100.7, 10.0.0.1",
    }
    assert client.post(URL, content=json.dumps(payload), headers=headers).status_code == 200
    [event] = events()
    assert event.user_agent == "PestPac-Webhooks/2"
    assert event.forwarded_for == "198.51.100.7, 10.0.0.1"
    assert event.client_ip  # the test client's address


def test_onboarded_service_order_is_stored_with_valid_signature(client, onboarded, secret):
    payload = order_event()
    resp = post(client, payload, signature=sign(payload["EntityBody"]))
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted"}
    [event] = events()
    assert (event.entity, event.action, event.pestpac_entity_id) == (
        "service_order",
        "update",
        1552079,
    )
    assert event.pestpac_bill_to_id == ONBOARDED_BILL_TO
    assert event.pestpac_location_id == STORE
    assert event.signature_status == "valid"
    assert event.status == "received"
    assert json.loads(event.raw_body) == payload


def test_events_outside_onboarded_bill_tos_are_not_stored(client, onboarded, secret):
    payload = order_event(bill_to_id=999999)
    assert post(client, payload, signature=sign(payload["EntityBody"])).status_code == 200
    assert events() == []


@pytest.mark.parametrize(
    ("signature", "expected"),
    [("0" * 64, "invalid"), (None, "missing")],
)
def test_bad_signatures_are_recorded_not_refused(client, onboarded, secret, signature, expected):
    assert post(client, order_event(), signature=signature).status_code == 200
    assert [e.signature_status for e in events()] == [expected]


def test_operator_without_a_secret_is_flagged(client, onboarded):
    payload = order_event()
    post(client, payload, signature=sign(payload["EntityBody"]))
    assert [e.signature_status for e in events()] == ["no_secret"]


def test_redelivery_is_stored_once(client, onboarded, secret):
    payload = order_event()
    for _ in range(2):
        assert post(client, payload, signature=sign(payload["EntityBody"])).status_code == 200
    assert len(events()) == 1


def test_unknown_tenant_is_dropped(client, onboarded):
    payload = order_event() | {"TenantId": "999999"}
    assert post(client, payload).status_code == 200
    assert events() == []


@pytest.mark.parametrize(
    ("entity_type", "action"),
    # Invoices are captured now (any action); Payment stands in as an uncaptured type.
    [("Service Order", "Archive"), ("Payment", "Create"), ("Bill To", "Post")],
)
def test_uncaptured_types_and_actions_are_dropped(client, onboarded, entity_type, action):
    payload = envelope(entity_type, ONBOARDED_BILL_TO, action, {"BillToID": ONBOARDED_BILL_TO})
    assert post(client, payload).status_code == 200
    assert events() == []


@pytest.mark.parametrize(
    ("payload", "stored"),
    [
        (envelope("Bill To", ONBOARDED_BILL_TO, "Update", {"BillToID": ONBOARDED_BILL_TO}), True),
        (envelope("Bill To", 123, "Update", {"BillToID": 123}), False),
        (envelope("Location", 555, "Create", {"BillToID": ONBOARDED_BILL_TO}), True),
        (envelope("Location", 555, "Create", {"BillToID": 123}), False),
        # A delete may come without a body: matched because we hold the location.
        (envelope("Location", STORE, "Delete", None), True),
        (envelope("Note", 77, "Create", {"LocationID": STORE}), True),
        (envelope("Note", 77, "Create", {"LocationID": 123}), False),
        # Technicians are operator-wide, so employees always match.
        (envelope("Employee", 1332, "Update", {"TechID": 1332}), True),
        (envelope("Service Order", 1, "Post", pestpac_order(1, STORE, ONBOARDED_BILL_TO)), True),
    ],
)
def test_bill_to_rule_per_entity(client, onboarded, payload, stored):
    assert post(client, payload).status_code == 200
    assert len(events()) == (1 if stored else 0)


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", json.dumps({"TenantId": TENANT, "EntityType": "Note", "Action": "Create"})],
)
def test_malformed_envelopes_are_rejected(client, onboarded, content):
    resp = client.post(URL, content=content, headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    assert events() == []


def test_oversized_bodies_are_rejected(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("WEBHOOK_MAX_BODY_BYTES", "100")
    get_settings.cache_clear()
    try:
        resp = client.post(URL, content="x" * 200, headers={"Content-Type": "application/json"})
        # Chunked: no Content-Length to refuse up front, so the stream itself is cut off.
        chunked = client.post(
            URL,
            content=(b"x" * 50 for _ in range(4)),
            headers={"Content-Type": "application/json"},
        )
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert resp.status_code == 413
    assert chunked.status_code == 413


def test_raw_bodies_are_cleared_after_retention(client, onboarded):
    post(client, order_event())
    post(client, order_event(action="Post"))
    old, recent = events()
    with SessionLocal() as db:
        db.execute(
            update(WebhookEvent)
            .where(WebhookEvent.id == old.id)
            .values(received_at=datetime.now(UTC) - timedelta(days=31))
        )
        db.commit()
        assert purge_raw_bodies(db) == 1
    by_id = {e.id: e for e in events()}
    assert by_id[old.id].raw_body is None and by_id[old.id].raw_body_purged_at is not None
    assert by_id[recent.id].raw_body is not None


def test_webhook_secret_is_write_only(client, world, pestpac):
    from tests.conftest import headers_for

    admin = headers_for(client, world.emails["admin_a"])
    url = f"/v1/operators/{world.op_a}/pestpac-connection"
    assert client.get(url, headers=admin).json()["has_webhook_secret"] is False
    resp = client.put(
        url,
        json={"client_id": "client-a", "username": "api-user-a", "webhook_secret": SECRET},
        headers=admin,
    )
    assert resp.status_code == 200
    assert resp.json()["has_webhook_secret"] is True
    assert SECRET not in resp.text


# --- Processing (service order handler) ---


def _posted_event(action: str = "Post", **body) -> dict:
    order = pestpac_order(1552079, STORE, ONBOARDED_BILL_TO, Posted=True, **body)
    return envelope("Service Order", 1552079, action, order)


def _process() -> int:
    worker._Stop.requested = False
    return worker.run_pending_webhooks()


def _order(pestpac_order_id: int) -> ServiceOrder | None:
    with SessionLocal() as db:
        return db.scalar(
            select(ServiceOrder).where(ServiceOrder.pestpac_order_id == pestpac_order_id)
        )


def test_order_event_queues_its_location_and_the_sync_marks_it_worked(client, onboarded, pestpac):
    worker._Stop.requested = False
    worker.run_pending()  # the onboarding sync, before PestPac lists the order
    pestpac.orders_by_location[STORE] = [
        pestpac_order(1552079, STORE, ONBOARDED_BILL_TO, Posted=True)
    ]
    post(client, _posted_event())

    assert _process() == 1
    [event] = events()
    assert event.status == "processed" and event.error is None and event.processed_at
    with SessionLocal() as db:
        job = db.get(SyncJob, event.sync_job_id)
        assert job.kind == "location_service_orders" and job.status == "queued"

    worker.run_pending()
    order = _order(1552079)
    assert order.posted and order.posted_at is not None


def test_events_for_one_location_share_a_job(client, onboarded):
    post(client, _posted_event(), timestamp="2026-10-21T22:24:30Z")
    post(client, _posted_event("Update"), timestamp="2026-10-21T22:24:33Z")
    assert _process() == 2
    first, second = events()
    assert first.sync_job_id is not None and first.sync_job_id == second.sync_job_id


def test_order_at_an_unsynced_location_queues_the_bill_to(client, onboarded):
    body = pestpac_order(1552079, 999999, ONBOARDED_BILL_TO, Posted=True)
    post(client, envelope("Service Order", 1552079, "Post", body))
    _process()
    [event] = events()
    with SessionLocal() as db:
        assert db.get(SyncJob, event.sync_job_id).kind == "bill_to_service_orders"


def test_order_without_a_target_is_failed_with_a_reason(client, world):
    with SessionLocal() as db:
        db.add(
            WebhookEvent(
                operator_id=world.op_a,
                entity=WebhookEntity.service_order,
                action="update",
                pestpac_entity_id=4242,
                signature_status="no_secret",
                body_sha256="1" * 64,
            )
        )
        db.commit()
    _process()
    [event] = events()
    assert event.status == "failed" and event.sync_job_id is None
    assert event.error == "No synced location or onboarded bill-to for this order"


def test_delete_and_inactive_bill_to_are_processed_without_a_sync(client, onboarded):
    body = pestpac_order(1552079, STORE, ONBOARDED_BILL_TO)
    post(
        client, envelope("Service Order", 1552079, "Delete", body), timestamp="2026-10-21T22:24:30Z"
    )
    post(client, _posted_event(), timestamp="2026-10-21T22:24:33Z")
    with SessionLocal() as db:  # deactivated after the post event was stored
        db.execute(update(BillTo).values(is_active=False))
        db.commit()
    assert _process() == 2
    assert [(e.action, e.status, e.sync_job_id) for e in events()] == [
        ("delete", "processed", None),
        ("post", "processed", None),
    ]


def test_entities_without_a_handler_stay_received(client, onboarded):
    note = {"NoteID": 77, "LocationID": STORE}
    post(client, envelope("Note", 77, "Create", note))
    assert _process() == 0
    assert [e.status for e in events()] == ["received"]


def test_handler_crash_is_recorded_not_retried(client, onboarded, monkeypatch):
    def boom(db, event):
        raise RuntimeError("bug")

    monkeypatch.setattr(webhook_handlers, "process", boom)
    post(client, _posted_event())
    assert _process() == 1
    [event] = events()
    assert (event.status, event.error) == ("failed", "Handler error: RuntimeError")
    assert _process() == 0


# --- Billed orders: PestPac no longer lists them; only the invoice remains ---

BILLED_ORDER = 1865079
BILLED_NUMBER = "3046886"


def _billed_invoice(**overrides) -> dict:
    fields = {
        "OrderID": BILLED_ORDER,
        "OrderNumber": BILLED_NUMBER,
        "LocationID": STORE,
        "BillToID": ONBOARDED_BILL_TO,
        "TechnicianComment": "Sealed gap by the CO2 tank.",
    }
    return pestpac_invoice(3500001, **(fields | overrides))


def _billed_event() -> dict:
    order = pestpac_order(
        BILLED_ORDER, STORE, ONBOARDED_BILL_TO, Posted=True, OrderNumber=BILLED_NUMBER
    )
    return envelope("Service Order", BILLED_ORDER, "Post", order)


def test_billed_order_is_stored_from_its_invoice(client, onboarded, pestpac):
    worker._Stop.requested = False
    worker.run_pending()  # onboarding sync; PestPac never lists the (billed) order
    pestpac.invoices[3500001] = _billed_invoice()
    post(client, _billed_event())
    [event] = events()
    with SessionLocal() as db:  # a note PestPac associated with the order, synced earlier
        db.add(
            Note(
                operator_id=event.operator_id,
                pestpac_note_id=990001,
                pestpac_order_id=BILLED_ORDER,
                pestpac_fetched_at=datetime.now(UTC),
            )
        )
        db.commit()

    assert _process() == 1
    [event] = events()
    assert event.status == "processed" and event.error is None
    order = _order(BILLED_ORDER)
    assert order.order_number == BILLED_NUMBER
    assert order.posted and order.posted_at and order.closed_at  # worked and billed
    assert order.pestpac_invoice_id == 3500001
    assert order.technician_comment == "Sealed gap by the CO2 tank."
    assert order.location_id is not None and order.work_date is not None
    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.pestpac_invoice_id == 3500001))
        assert invoice.service_order_id == order.id
        note = db.scalar(select(Note).where(Note.pestpac_note_id == 990001))
        assert note.service_order_id == order.id

    # The queued location sync doesn't list it, and leaves it billed.
    worker.run_pending()
    assert _order(BILLED_ORDER).closed_at is not None


def test_open_order_is_left_to_the_sync(client, onboarded, pestpac):
    post(client, _billed_event())  # no invoice: the order is still open
    _process()
    [event] = events()
    assert event.status == "processed" and event.sync_job_id is not None
    assert _order(BILLED_ORDER) is None


def test_invoice_for_another_order_is_not_used(client, onboarded, pestpac):
    pestpac.invoices[3500001] = _billed_invoice(OrderID=7777777)
    post(client, _billed_event())
    _process()
    assert _order(BILLED_ORDER) is None


def test_invoice_search_failure_fails_the_event(client, onboarded, pestpac):
    pestpac.invoice_search_status = 500
    post(client, _billed_event())
    _process()
    [event] = events()
    assert event.status == "failed" and "billed" in event.error
    assert event.sync_job_id is not None  # the location sync is still queued
    assert _order(BILLED_ORDER) is None


def test_requeue_fills_orders_billed_before_invoices_were_used(client, onboarded, pestpac):
    pestpac.invoice_search_status = 500  # handled without its invoice (as before this fix)
    post(client, _billed_event())
    _process()
    pestpac.invoice_search_status = 200
    pestpac.invoices[3500001] = _billed_invoice()

    with SessionLocal() as db:
        assert webhook_handlers.requeue_unstored_orders(db) == 1
        assert webhook_handlers.requeue_unstored_orders(db) == 0  # already queued
    assert _process() == 1
    assert _order(BILLED_ORDER).pestpac_invoice_id == 3500001
    with SessionLocal() as db:
        assert webhook_handlers.requeue_unstored_orders(db) == 0  # stored now


def test_order_stored_meanwhile_by_another_worker_is_used(client, onboarded):
    """Two workers can handle two events for the same billed order at once: the later insert
    gives way to the stored copy instead of failing the event."""
    from app.schemas.pestpac import PestPacInvoiceDetails
    from app.services import invoices

    post(client, _billed_event())
    [event] = events()
    with SessionLocal() as db:
        bill_to = db.scalar(select(BillTo).where(BillTo.pestpac_bill_to_id == ONBOARDED_BILL_TO))
        details = PestPacInvoiceDetails.from_api(_billed_invoice())
        now = datetime.now(UTC)
        first = invoices._order_from_invoice(
            db, event.operator_id, details, bill_to.id, None, None, now
        )
        db.commit()
        again = invoices._order_from_invoice(
            db, event.operator_id, details, bill_to.id, None, None, now
        )
        db.commit()
        assert again.id == first.id
        count = db.scalar(
            select(func.count())
            .select_from(ServiceOrder)
            .where(ServiceOrder.pestpac_order_id == BILLED_ORDER)
        )
        assert count == 1
