from decimal import Decimal

from sqlalchemy import select

from app import worker
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Invoice, Note, ServiceOrder, SyncJob, Tenant, WebhookEvent
from tests.conftest import (
    INVOICE_FIXTURE,
    INVOICE_URL,
    ONBOARDED_BILL_TO,
    WORLD_WEBHOOK_SHA,
    pestpac_invoice,
    pestpac_note,
    pestpac_note_detail,
    pestpac_order,
)
from tests.test_notes import _store_id
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


# --- Order sync -> GET /Locations/{id}/serviceHistory ---


def _posted_order(**overrides):
    return pestpac_order(
        ORDER_ID, STORE, ONBOARDED_BILL_TO, Posted=True, OrderNumber=ORDER_NUMBER, **overrides
    )


def _invoice_progress() -> dict:
    with SessionLocal() as db:
        job = db.scalar(select(SyncJob).order_by(SyncJob.created_at.desc()))
        return job.progress["invoices"]


def _invoice_fetches(pestpac) -> int:
    return sum(bool(INVOICE_URL.search(c.request.url)) for c in pestpac.calls)


def test_order_sync_stores_the_locations_invoices_once(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [_posted_order()]
    pestpac.invoices[3494466] = pestpac_invoice()
    _drain()  # onboarding sync

    assert _invoice_progress() == {
        "listed": 1,
        "held": 0,
        "stored": 1,
        "orders_created": 0,
        "not_found": 0,
        "linked": 0,
    }
    invoice = _invoice()
    assert invoice.service_order_id == _order().id
    # Fetched in full: the history leaves out line items and the technician comment.
    assert [line.extended_price for line in invoice.lines] == [Decimal("120.00")]
    assert _order().technician_comment is not None

    fetches = _invoice_fetches(pestpac)
    _drain_with_order_sync(client, onboarded)
    assert _invoice_progress()["held"] == 1
    assert _invoice_fetches(pestpac) == fetches  # held: not fetched again


def test_an_order_we_never_saw_is_stored_from_its_invoice(client, onboarded, pestpac):
    """RAMP program nights are billed before any order sync lists them."""
    night = 1854800
    pestpac.orders_by_location[STORE] = [_posted_order()]
    pestpac.invoices[3494466] = pestpac_invoice()
    pestpac.invoices[3494470] = pestpac_invoice(
        3494470,
        OrderID=night,
        OrderNumber="2596398",
        InvoiceNumber="A2596398",
        ServiceCode="RAMP 1",
        TechnicianComment="Mass trapped entire store; two live mice upstairs.",
    )
    note = pestpac_note(77, text="Service: RAMP 1\nNight 1 of mass trapping.")
    pestpac.notes_by_location[STORE] = [note]
    pestpac.note_details[77] = pestpac_note_detail(note, location_id=STORE, order_id=night)
    _drain()

    progress = _invoice_progress()
    assert (progress["listed"], progress["stored"], progress["orders_created"]) == (2, 2, 1)
    with SessionLocal() as db:
        order = db.scalar(select(ServiceOrder).where(ServiceOrder.pestpac_order_id == night))
        assert (order.order_number, order.service_code, order.posted) == ("2596398", "RAMP 1", True)
        assert order.closed_at is not None and order.pestpac_invoice_id == 3494470
        assert order.technician_comment.startswith("Mass trapped")
        assert order.location_id is not None
        assert db.scalar(select(Note.service_order_id).where(Note.pestpac_note_id == 77)) == (
            order.id
        )


def test_a_worked_order_with_no_invoice_yet_waits(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [_posted_order()]
    _drain()
    assert _invoice_progress() == {
        "listed": 0,
        "held": 0,
        "stored": 0,
        "orders_created": 0,
        "not_found": 0,
        "linked": 0,
    }
    assert _order().pestpac_invoice_id is None


def test_service_history_is_paged(client, onboarded, pestpac, monkeypatch):
    monkeypatch.setenv("PESTPAC_PAGE_SIZE", "2")
    get_settings.cache_clear()
    try:
        for n in range(5):
            pestpac.invoices[3494466 + n] = pestpac_invoice(
                3494466 + n, OrderID=ORDER_ID + n, OrderNumber=str(3048012 + n)
            )
        _drain()
        assert _invoice_progress()["listed"] == 5
        history = f"/Locations/{STORE}/serviceHistory"
        pages = [c.request.url for c in pestpac.calls if history in c.request.url]
        assert len(pages) == 3  # 2 + 2 + a short page of 1
    finally:
        get_settings.cache_clear()


def test_order_sync_links_an_invoice_it_already_holds_without_fetching(client, onboarded, pestpac):
    """An invoice stored before we held its order (e.g. from a webhook) is linked by OrderID."""
    from app.schemas.pestpac import PestPacInvoiceDetails
    from app.services import invoices, pestpac_connection
    from app.services.technicians import TechnicianResolver

    with SessionLocal() as db:
        operator = db.scalar(select(Tenant).where(Tenant.pestpac_tenant_id == "115060"))
        client_ = pestpac_connection.get_pestpac_client(db, operator)
        invoices.upsert_invoice(
            db,
            operator.id,
            PestPacInvoiceDetails.from_api(pestpac_invoice()),
            TechnicianResolver(db, client_, operator.id),
        )
        db.commit()
    assert _invoice().service_order_id is None  # we don't hold the order yet
    pestpac.orders_by_location[STORE] = [_posted_order()]
    pestpac.invoices[3494466] = pestpac_invoice()  # listed in the history: held, not fetched
    _drain()  # onboarding sync stores the order

    progress = _invoice_progress()
    assert (progress["held"], progress["linked"]) == (1, 1)
    assert _invoice().service_order_id == _order().id
    assert _order().pestpac_invoice_id == 3494466
    assert _invoice_fetches(pestpac) == 0


def test_service_history_failure_keeps_the_orders(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [_posted_order()]
    pestpac.service_history_status = 500
    _drain()
    with SessionLocal() as db:
        job = db.scalar(select(SyncJob).order_by(SyncJob.created_at.desc()))
        # Every location's history is read, so all three of the bill-to's fail.
        assert job.status == "partial" and "invoices failed for 3" in job.error
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


def test_invoiced_orders_sort_by_invoice_date(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [
        _posted_order(),
        pestpac_order(1854700, STORE, ONBOARDED_BILL_TO, Posted=True, OrderNumber="3049999"),
    ]
    pestpac.invoices[3494466] = pestpac_invoice(InvoiceDate="2026-10-22T00:00:00")
    pestpac.invoices[3494467] = pestpac_invoice(
        3494467,
        OrderID=1854700,
        OrderNumber="3049999",
        InvoiceNumber="A3049999",
        InvoiceDate="2026-09-01T00:00:00",
    )
    _drain()
    path = f"/v1/bill-tos/{onboarded['bill_to_id']}/invoiced-orders"

    def ids(**params):
        page = client.get(path, params=params, headers=onboarded["headers"]).json()
        return [i["pestpac_invoice_id"] for i in page["items"]]

    assert ids() == [3494466, 3494467]  # newest first by default
    assert ids(sort="asc") == [3494467, 3494466]
    assert client.get(path, params={"sort": "up"}, headers=onboarded["headers"]).status_code == 422


def test_a_locations_orders_are_listed_as_posted_invoiced_and_open(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [
        _posted_order(WorkDate="2026-10-01T09:00:00"),  # invoiced below
        pestpac_order(
            1854700,
            STORE,
            ONBOARDED_BILL_TO,
            Posted=True,
            OrderNumber="3049999",
            WorkDate="2026-10-05T09:00:00",
        ),
        pestpac_order(
            1854701,
            STORE,
            ONBOARDED_BILL_TO,
            Posted=False,
            OrderNumber="3050000",
            WorkDate="2026-11-02T09:00:00",
        ),
    ]
    # Another location's worked order: not this location's.
    pestpac.orders_by_location[900002] = [
        pestpac_order(1854800, 900002, ONBOARDED_BILL_TO, Posted=True, OrderNumber="3051111")
    ]
    pestpac.invoices[3494466] = pestpac_invoice()  # bills ORDER_ID only
    _drain()
    base = f"/v1/locations/{_store_id(client, onboarded)}"

    def ids(kind, **params):
        resp = client.get(
            f"{base}/{kind}-service-orders", params=params, headers=onboarded["headers"]
        )
        assert resp.status_code == 200, resp.text
        return [o["pestpac_order_id"] for o in resp.json()["items"]]

    assert ids("posted") == [1854700]
    assert ids("invoiced") == [ORDER_ID]
    assert ids("open") == [1854701]
    assert ids("posted", q="3049999") == [1854700]
