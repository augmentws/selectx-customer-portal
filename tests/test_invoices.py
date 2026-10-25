from sqlalchemy import select

from app import worker
from app.db.session import SessionLocal
from app.models import Invoice, ServiceOrder, SyncJob, Tenant, WebhookEvent
from tests.conftest import (
    INVOICE_FIXTURE,
    ONBOARDED_BILL_TO,
    WORLD_WEBHOOK_SHA,
    pestpac_invoice,
    pestpac_order,
)
from tests.test_webhooks import envelope, post

STORE = 900001
ORDER_ID = INVOICE_FIXTURE["OrderID"]  # 1854693
ORDER_NUMBER = INVOICE_FIXTURE["OrderNumber"]  # "3048012"


def _drain():
    worker._Stop.requested = False
    return worker.run_pending()


def _invoice(pestpac_invoice_id: int = 3494466) -> Invoice | None:
    with SessionLocal() as db:
        invoice = db.scalar(select(Invoice).where(Invoice.pestpac_invoice_id == pestpac_invoice_id))
        if invoice is not None:
            invoice.lines  # load before the session closes  # noqa: B018
        return invoice


def _order() -> ServiceOrder:
    with SessionLocal() as db:
        return db.scalar(select(ServiceOrder).where(ServiceOrder.pestpac_order_id == ORDER_ID))


def _event() -> WebhookEvent:
    with SessionLocal() as db:
        return db.scalar(
            select(WebhookEvent)
            .where(WebhookEvent.body_sha256 != WORLD_WEBHOOK_SHA)
            .order_by(WebhookEvent.received_at.desc())
        )


def _invoice_webhook(client, action="Create", invoice_id=3494466, bill_to_id=ONBOARDED_BILL_TO):
    body = {"InvoiceID": invoice_id, "BillToID": bill_to_id, "LocationID": STORE}
    assert post(client, envelope("Invoice", invoice_id, action, body)).status_code == 200


# --- Webhook -> GET /Invoices/{id} ---


def test_invoice_webhook_fetches_and_stores_whitelisted_fields(client, onboarded, pestpac):
    _drain()  # onboarding sync
    pestpac.invoices[3494466] = pestpac_invoice()
    _invoice_webhook(client)
    _drain()

    assert _event().status == "processed"
    invoice = _invoice()
    assert invoice.invoice_number == "A3048012" and invoice.order_number == ORDER_NUMBER
    assert (str(invoice.total), str(invoice.balance), str(invoice.cost)) == (
        "130.65",
        "130.65",
        "12.50",
    )
    assert invoice.invoice_date.isoformat() == "2026-10-22T00:00:00"
    assert invoice.due_date.isoformat() == "2026-11-21T00:00:00"
    assert (invoice.time_range, invoice.duration, invoice.origin) == ("11PM-5AM", 59, "OneTime")
    assert invoice.technician_comment == "Inspection completed. No activity found."
    assert invoice.location_id is not None and invoice.batch_number == 460858
    # Position-1 technician only, linked to our technician by TechID.
    assert invoice.pestpac_tech_id == 1332 and invoice.technician_id is not None
    [line] = invoice.lines
    assert (line.service_code, str(line.unit_price), str(line.extended_price), line.taxable) == (
        "RAMP MONITOR",
        "120.0000",
        "120.00",
        True,
    )
    # Never kept: tax, terms, contacts, technician pay, user-defined fields.
    for column in ("tax", "terms", "commission", "bonus", "share", "user_defined_fields"):
        assert not hasattr(invoice, column)


def test_invoice_completes_its_order(client, onboarded, pestpac):
    _drain()
    # We saw the order open and never saw it posted; then it was billed.
    pestpac.orders_by_location[STORE] = [pestpac_order(ORDER_ID, STORE, ONBOARDED_BILL_TO)]
    pestpac.invoices[3494466] = pestpac_invoice()
    _drain_with_order_sync(client, onboarded)
    _invoice_webhook(client)
    _drain()

    order = _order()
    assert order.posted and order.posted_at is not None
    assert order.pestpac_invoice_id == 3494466
    assert order.technician_comment == "Inspection completed. No activity found."
    assert _invoice().service_order_id == order.id


def _drain_with_order_sync(client, onboarded):
    resp = client.post(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/service-orders/sync", headers=onboarded["headers"]
    )
    assert resp.status_code == 202
    _drain()


def test_invoice_of_another_bill_to_is_not_stored(client, onboarded, pestpac):
    _drain()
    pestpac.invoices[3494466] = pestpac_invoice(BillToID=555555)
    _invoice_webhook(client)  # captured: the webhook body names our bill-to
    _drain()
    assert _event().status == "processed"
    assert _invoice() is None


def test_deleted_or_missing_invoice_is_flagged_not_deleted(client, onboarded, pestpac):
    _drain()
    pestpac.invoices[3494466] = pestpac_invoice()
    _invoice_webhook(client)
    _drain()

    _invoice_webhook(client, action="Delete")
    _drain()
    assert _invoice().removed_at is not None

    _invoice_webhook(client, invoice_id=3499999)  # PestPac doesn't have it
    _drain()
    event = _event()
    assert (event.status, event.error) == ("failed", "Invoice not found in PestPac")


def test_pestpac_failure_is_recorded_on_the_event(client, onboarded, pestpac):
    _drain()
    pestpac.invoices[3494466] = 503
    _invoice_webhook(client)
    _drain()
    event = _event()
    assert event.status == "failed" and "503" in event.error


# --- Order sync -> GET /Invoices?orderNumber= ---


def _posted_order(**overrides):
    return pestpac_order(
        ORDER_ID, STORE, ONBOARDED_BILL_TO, Posted=True, OrderNumber=ORDER_NUMBER, **overrides
    )


def test_order_sync_fetches_invoices_for_worked_orders_once(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [_posted_order()]
    pestpac.invoices[3494466] = pestpac_invoice()
    _drain()  # onboarding sync

    with SessionLocal() as db:
        job = db.scalar(select(SyncJob).order_by(SyncJob.created_at.desc()))
        assert job.status == "succeeded"
        assert job.progress["invoices"] == {"orders_checked": 1, "stored": 1, "not_invoiced": 0}
    assert _invoice().service_order_id == _order().id

    _drain_with_order_sync(client, onboarded)
    with SessionLocal() as db:
        job = db.scalar(select(SyncJob).order_by(SyncJob.created_at.desc()))
        assert job.progress["invoices"]["orders_checked"] == 0  # it has one now


def test_worked_order_not_invoiced_yet_is_tried_again(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [_posted_order()]
    _drain()
    _drain_with_order_sync(client, onboarded)
    with SessionLocal() as db:
        job = db.scalar(select(SyncJob).order_by(SyncJob.created_at.desc()))
        assert job.progress["invoices"] == {"orders_checked": 1, "stored": 0, "not_invoiced": 1}


def test_invoice_search_failure_keeps_the_orders(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [_posted_order()]
    pestpac.invoice_search_status = 500
    _drain()
    with SessionLocal() as db:
        job = db.scalar(select(SyncJob).order_by(SyncJob.created_at.desc()))
        assert job.status == "partial" and "invoices failed for 1" in job.error
    assert _order().posted


# --- API ---


def test_location_invoices_need_billing_read(client, onboarded, pestpac, world):
    pestpac.orders_by_location[STORE] = [_posted_order()]
    pestpac.invoices[3494466] = pestpac_invoice()
    _drain()
    location_id = _invoice().location_id
    resp = client.get(f"/v1/locations/{location_id}/invoices", headers=onboarded["headers"])
    assert resp.status_code == 200
    page = resp.json()
    assert page["total"] == 1
    item = page["items"][0]
    assert (item["invoice_number"], item["total"], item["technician_name"]) == (
        "A3048012",
        "130.65",
        "Pat Tech",  # our technician record for TechID 1332, not the invoice's copy of the name
    )
    assert [line["extended_price"] for line in item["lines"]] == ["120.00"]


def test_search_takes_the_returned_invoice_object(pestpac, world):
    """PestPac answers the orderNumber search with the invoice object itself."""
    from app.services import pestpac_connection
    from app.services.invoices import fetch_invoices_for_order

    pestpac.invoices[3494466] = pestpac_invoice()
    with SessionLocal() as db:
        operator = db.get(Tenant, world.op_a)
        client = pestpac_connection.get_pestpac_client(db, operator)
    [found] = fetch_invoices_for_order(client, ORDER_NUMBER)
    assert found.pestpac_invoice_id == 3494466
    assert fetch_invoices_for_order(client, "999") == []  # 404: not invoiced yet


def test_invoiced_orders_leave_posted_and_list_under_their_invoice(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [
        _posted_order(),
        pestpac_order(1854700, STORE, ONBOARDED_BILL_TO, Posted=True, OrderNumber="3049999"),
    ]
    pestpac.invoices[3494466] = pestpac_invoice()  # bills ORDER_ID only
    _drain()
    headers = onboarded["headers"]
    bill_to_id = onboarded["bill_to_id"]
    company_id = client.get(f"/v1/bill-tos/{bill_to_id}", headers=headers).json()["company_id"]

    for scope in (f"/v1/bill-tos/{bill_to_id}", f"/v1/companies/{company_id}"):
        posted = client.get(f"{scope}/posted-service-orders", headers=headers).json()
        assert [o["pestpac_order_id"] for o in posted["items"]] == [1854700]

        invoiced = client.get(f"{scope}/invoiced-orders", headers=headers).json()
        # The company also holds the test world's invoice.
        [item] = [i for i in invoiced["items"] if i["pestpac_invoice_id"] == 3494466]
        assert item["invoice_number"] == "A3048012" and item["location_name"] is not None
        assert item["service_order"]["pestpac_order_id"] == ORDER_ID
        assert item["service_order"]["technician_comment"] is not None
