import pytest

from app.core.config import get_settings
from tests.conftest import headers_for, pestpac_note, pestpac_note_detail, pestpac_order
from tests.test_service_orders import BILL_TO, _latest_job, _run_worker, _sync

STORE = 900001


@pytest.fixture
def page_size(monkeypatch):
    def use(size: int):
        monkeypatch.setenv("PESTPAC_PAGE_SIZE", str(size))
        get_settings.cache_clear()

    yield use
    monkeypatch.undo()
    get_settings.cache_clear()


def _store_id(client, onboarded):
    locations = client.get(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/locations", headers=onboarded["headers"]
    ).json()
    return next(loc["id"] for loc in locations if loc["pestpac_location_id"] == STORE)


def _location_notes(client, onboarded):
    resp = client.get(
        f"/v1/locations/{_store_id(client, onboarded)}/notes", headers=onboarded["headers"]
    )
    assert resp.status_code == 200
    return resp.json()


def _note_detail_calls(pestpac) -> int:
    return sum("/v1/Notes/" in c.request.url for c in pestpac.calls)


def _add_notes(pestpac, *notes):
    """Notes as (list item, detail) pairs listed under STORE."""
    pestpac.notes_by_location[STORE] = [item for item, _ in notes]
    for item, detail in notes:
        pestpac.note_details[item["NoteID"]] = detail


def test_full_history_is_stored_with_paging(client, onboarded, pestpac, page_size):
    page_size(2)
    items = [pestpac_note(n, text=f"note {n}") for n in (1, 2, 3)]
    _add_notes(pestpac, *[(i, pestpac_note_detail(i, location_id=STORE)) for i in items])
    _run_worker()

    job = _latest_job(client, onboarded)
    assert job["status"] == "succeeded"
    assert job["progress"]["notes"]["added"] == 3
    assert sorted(n["pestpac_note_id"] for n in _location_notes(client, onboarded)) == [1, 2, 3]
    assert _note_detail_calls(pestpac) == 3


def test_known_notes_are_not_fetched_again_but_edits_are_picked_up(client, onboarded, pestpac):
    item = pestpac_note(1, text="original")
    _add_notes(pestpac, (item, pestpac_note_detail(item, location_id=STORE)))
    _run_worker()
    calls = _note_detail_calls(pestpac)

    pestpac.notes_by_location[STORE] = [pestpac_note(1, text="edited in PestPac")]
    job = _sync(client, onboarded)
    assert _note_detail_calls(pestpac) == calls  # no second /Notes/{id}
    assert job["progress"]["notes"]["updated"] == 1
    assert _location_notes(client, onboarded)[0]["note"] == "edited in PestPac"


def test_note_links_to_our_order_and_its_invoice(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [pestpac_order(1863232, STORE, BILL_TO, Posted=True)]
    item = pestpac_note(10)
    _add_notes(
        pestpac,
        (item, pestpac_note_detail(item, location_id=STORE, order_id=1863232, invoice_id=3287489)),
    )
    _run_worker()

    orders = client.get(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/service-orders", headers=onboarded["headers"]
    ).json()
    order = orders[0]
    assert order["pestpac_invoice_id"] == 3287489
    order_notes = client.get(
        f"/v1/service-orders/{order['id']}/notes", headers=onboarded["headers"]
    ).json()
    assert [n["pestpac_note_id"] for n in order_notes] == [10]
    assert order_notes[0]["pestpac_order_id"] == 1863232


def test_notes_for_other_orders_stay_location_notes(client, onboarded, pestpac):
    item = pestpac_note(11)
    _add_notes(pestpac, (item, pestpac_note_detail(item, location_id=STORE, order_id=42)))
    _run_worker()
    note = _location_notes(client, onboarded)[0]
    assert note["pestpac_order_id"] == 42
    assert note["service_order_id"] is None


def test_invoice_arriving_after_posting_is_picked_up(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [pestpac_order(5, STORE, BILL_TO, Posted=True)]
    item = pestpac_note(12)
    _add_notes(pestpac, (item, pestpac_note_detail(item, location_id=STORE, order_id=5)))
    _run_worker()
    orders_url = f"/v1/bill-tos/{onboarded['bill_to_id']}/service-orders"
    assert (
        client.get(orders_url, headers=onboarded["headers"]).json()[0]["pestpac_invoice_id"] is None
    )

    pestpac.note_details[12] = pestpac_note_detail(
        item, location_id=STORE, order_id=5, invoice_id=77
    )
    job = _sync(client, onboarded)
    assert job["progress"]["notes"]["invoices_found"] == 1
    assert (
        client.get(orders_url, headers=onboarded["headers"]).json()[0]["pestpac_invoice_id"] == 77
    )


def test_authors_link_to_seeded_technicians(client, onboarded, pestpac):
    tech_item = pestpac_note(20, user="TECH01")
    office_item = pestpac_note(21, user="OFFICE1")
    _add_notes(
        pestpac,
        (tech_item, pestpac_note_detail(tech_item, location_id=STORE)),
        (office_item, pestpac_note_detail(office_item, location_id=STORE)),
    )
    _run_worker()

    job = _latest_job(client, onboarded)
    assert job["progress"]["technicians"]["added"] == 1
    authors = {
        n["pestpac_note_id"]: n["created_by_name"] for n in _location_notes(client, onboarded)
    }
    assert authors == {20: "Pat Tech", 21: "OFFICE1"}
    # Seeded up front, so no per-tech lookup was needed.
    assert not any("/technicians/" in c.request.url for c in pestpac.calls)


def test_technician_seeding_failure_does_not_fail_the_job(client, onboarded, pestpac):
    pestpac.technicians_listed = 503
    _run_worker()
    job = _latest_job(client, onboarded)
    assert job["status"] == "succeeded"
    assert "error" in job["progress"]["technicians"]


def test_notes_failure_keeps_orders_and_marks_partial(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [pestpac_order(1, STORE, BILL_TO)]
    pestpac.notes_by_location[STORE] = 500
    _run_worker()
    job = _latest_job(client, onboarded)
    assert job["status"] == "partial"
    assert [f["pestpac_location_id"] for f in job["progress"]["notes_failed_locations"]] == [STORE]
    orders = client.get(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/service-orders", headers=onboarded["headers"]
    ).json()
    assert len(orders) == 1


def test_staff_can_read_notes(client, world, onboarded, pestpac):
    item = pestpac_note(30)
    _add_notes(pestpac, (item, pestpac_note_detail(item, location_id=STORE)))
    _run_worker()
    staff = headers_for(client, world.emails["staff_a"])
    resp = client.get(f"/v1/locations/{_store_id(client, onboarded)}/notes", headers=staff)
    assert resp.status_code == 200 and len(resp.json()) == 1
