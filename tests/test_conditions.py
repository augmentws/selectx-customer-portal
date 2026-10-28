from tests.conftest import (
    pestpac_condition,
    pestpac_condition_detail,
    pestpac_document,
    pestpac_inspection,
    pestpac_order,
)
from tests.test_documents import _documents, _sync_locations
from tests.test_notes import STORE, _store_id
from tests.test_service_orders import _run_worker, _sync

PHOTO = b"\xff\xd8\xff\xe0 condition photo"


def _conditions(client, onboarded):
    resp = client.get(
        f"/v1/locations/{_store_id(client, onboarded)}/conditions", headers=onboarded["headers"]
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _detail_calls(pestpac) -> int:
    return sum("/v1/Conditions/" in c.request.url for c in pestpac.calls)


def _open_condition(pestpac, issue_id=41008, **list_overrides):
    item = pestpac_condition(issue_id, STORE, **list_overrides)
    pestpac.conditions_by_location[STORE] = [item]
    pestpac.condition_details[issue_id] = pestpac_condition_detail(
        item,
        inspections=[
            pestpac_inspection(1862519, "2026-10-15T14:21:40.57", ""),
            pestpac_inspection(1862519, "2026-10-15T14:21:40.777", ""),  # PestPac's near-duplicate
            pestpac_inspection(1865005, "2026-10-22T19:14:49.66", "Condition is still open"),
        ],
        documents=[
            pestpac_document(
                463,
                document_type="ConditionDocument",
                name="Stagnant water interior_1322748_0.jpg",
                date="2026-10-15T14:21:41.227",
                file_name="2026_0.jpg.jpg",
            )
        ],
    )
    pestpac.document_files[463] = (200, "image/jpeg", PHOTO)
    return item


def test_open_conditions_are_stored_with_inspections_and_documents(client, onboarded, pestpac):
    pestpac.orders_by_location[STORE] = [pestpac_order(1865005, STORE, 180020)]
    _run_worker()  # the onboarding order sync, so the condition's order is ours
    _open_condition(pestpac)  # after it: order syncs fetch conditions too
    job = _sync_locations(client, onboarded)

    assert job["status"] == "succeeded"
    assert job["progress"]["conditions"]["added"] == 1
    assert job["progress"]["conditions"]["details_fetched"] == 1
    assert job["progress"]["conditions"]["documents_linked"] == 1
    assert any(c.request.url.endswith(f"/Locations/{STORE}/conditions") for c in pestpac.calls)

    [condition] = _conditions(client, onboarded)
    assert condition["pestpac_issue_id"] == 41008
    assert condition["status"] == "Open" and condition["severity"] == "Medium"
    assert condition["area_hierarchy"] == "Restrooms -> Mens Room"
    assert condition["opened_by_user"] == "ADMN"
    assert condition["last_inspected_date"].startswith("2026-10-22T19:14:49")
    assert condition["service_order_id"] is not None
    inspections = condition["inspections"]
    assert [i["comment"] for i in inspections] == [None, None, "Condition is still open"]
    assert inspections[2]["service_order_id"] == condition["service_order_id"]
    assert inspections[0]["service_order_id"] is None  # OrderID 1862519 isn't ours

    [photo] = condition["documents"]
    assert photo["document_type"] == "ConditionDocument" and photo["pestpac_document_id"] == 463
    assert photo["has_file"]  # fetched in the same run
    assert any(d["pestpac_document_id"] == 463 for d in _documents(client, onboarded))


def test_details_are_fetched_again_only_when_the_condition_changes(client, onboarded, pestpac):
    item = _open_condition(pestpac)
    _sync_locations(client, onboarded)
    calls = _detail_calls(pestpac)

    _sync_locations(client, onboarded)
    assert _detail_calls(pestpac) == calls  # LastInspectedDate unchanged

    item["LastInspectedDate"] = "2026-10-29T10:00:00"
    detail = pestpac.condition_details[41008]
    detail["Inspections"] = detail["Inspections"] + [
        pestpac_inspection(1870000, "2026-10-29T10:00:00", "Resolved soon")
    ]
    job = _sync_locations(client, onboarded)
    assert _detail_calls(pestpac) == calls + 1
    assert job["progress"]["conditions"]["details_fetched"] == 1
    [condition] = _conditions(client, onboarded)
    assert len(condition["inspections"]) == 4  # replaced, not appended to
    assert condition["inspections"][-1]["comment"] == "Resolved soon"


def test_a_document_already_listed_for_the_location_is_linked_not_duplicated(
    client, onboarded, pestpac
):
    _open_condition(pestpac)
    pestpac.documents_by_location[STORE] = [
        pestpac_document(463, document_type="ConditionDocument", file_name="2026_0.jpg.jpg")
    ]
    _sync_locations(client, onboarded)
    docs = _documents(client, onboarded)
    assert [d["pestpac_document_id"] for d in docs] == [463]
    assert _conditions(client, onboarded)[0]["documents"][0]["id"] == docs[0]["id"]


def test_condition_documents_are_kept_when_the_location_list_omits_them(client, onboarded, pestpac):
    _open_condition(pestpac)
    _sync_locations(client, onboarded)
    job = _sync_locations(client, onboarded)  # the location's own list never had 463
    assert job["progress"]["documents"]["removed"] == 0
    assert len(_conditions(client, onboarded)[0]["documents"]) == 1


def test_a_condition_no_longer_open_is_fetched_once_to_record_its_closing(
    client, onboarded, pestpac
):
    item = _open_condition(pestpac)
    _sync_locations(client, onboarded)

    pestpac.conditions_by_location[STORE] = []
    pestpac.condition_details[41008] = pestpac_condition_detail(
        item, Status="Closed", DateClosed="2026-10-30T09:00:00"
    )
    job = _sync_locations(client, onboarded)
    assert job["progress"]["conditions"]["closed"] == 1
    [condition] = _conditions(client, onboarded)
    assert condition["status"] == "Closed"
    assert condition["date_closed"].startswith("2026-10-30T09:00")

    calls = _detail_calls(pestpac)
    _sync_locations(client, onboarded)
    assert _detail_calls(pestpac) == calls  # closed: not fetched again


def test_closed_conditions_are_listed_and_stored(client, onboarded, pestpac):
    """No status filter: conditions closed before our first sync are the remediation history."""
    _run_worker()  # the onboarding order sync, before the condition exists
    item = _open_condition(pestpac, status="Closed")
    pestpac.condition_details[41008] = pestpac_condition_detail(
        item, Status="Closed", DateClosed="2026-10-20T09:00:00"
    )
    job = _sync_locations(client, onboarded)
    assert job["progress"]["conditions"]["added"] == 1
    assert not any("status=" in c.request.url for c in pestpac.calls)
    [condition] = _conditions(client, onboarded)
    assert condition["status"] == "Closed"
    assert condition["date_closed"].startswith("2026-10-20T09:00")

    calls = _detail_calls(pestpac)
    _sync_locations(client, onboarded)
    assert _detail_calls(pestpac) == calls  # unchanged: not fetched again


def test_a_condition_listed_as_closed_is_fetched_to_record_its_closing(client, onboarded, pestpac):
    item = _open_condition(pestpac)
    _sync_locations(client, onboarded)

    closed = {**item, "Status": "Closed"}
    pestpac.conditions_by_location[STORE] = [closed]
    pestpac.condition_details[41008] = pestpac_condition_detail(
        closed, DateClosed="2026-10-30T09:00:00"
    )
    calls = _detail_calls(pestpac)
    job = _sync_locations(client, onboarded)
    assert _detail_calls(pestpac) == calls + 1
    assert job["progress"]["conditions"]["closed"] == 1
    [condition] = _conditions(client, onboarded)
    assert condition["status"] == "Closed"
    assert condition["date_closed"].startswith("2026-10-30T09:00")


def test_a_condition_pestpac_no_longer_has_is_marked_removed(client, onboarded, pestpac):
    _open_condition(pestpac)
    _sync_locations(client, onboarded)

    pestpac.conditions_by_location[STORE] = []
    del pestpac.condition_details[41008]  # 404
    job = _sync_locations(client, onboarded)
    assert job["progress"]["conditions"]["removed"] == 1
    assert _conditions(client, onboarded) == []


def test_conditions_failure_fails_only_that_location(client, onboarded, pestpac):
    _open_condition(pestpac)
    pestpac.condition_details[41008] = 500
    job = _sync_locations(client, onboarded)
    assert job["status"] == "partial"
    [failure] = job["progress"]["failed_locations"]
    assert failure["pestpac_location_id"] == STORE
    assert job["progress"]["locations_done"] == 3
    assert _conditions(client, onboarded) == []  # the location's lists rolled back together


def test_an_order_sync_also_syncs_the_locations_conditions(client, onboarded, pestpac):
    """A posted order (webhook or Sync) is when a technician's new conditions appear."""
    _open_condition(pestpac)
    job = _sync(client, onboarded)
    assert job["status"] == "succeeded"
    assert job["progress"]["conditions"]["added"] == 1
    [condition] = _conditions(client, onboarded)
    assert condition["pestpac_issue_id"] == 41008
    # Its documents are stored as rows; files wait for "Sync location".
    [document] = condition["documents"]
    assert not any("/download" in c.request.url for c in pestpac.calls)
    assert document["has_file"] is False


def test_a_conditions_failure_leaves_the_orders_and_makes_the_job_partial(
    client, onboarded, pestpac
):
    pestpac.orders_by_location[STORE] = [pestpac_order(1865005, STORE, 180020)]
    pestpac.conditions_by_location[STORE] = 500
    job = _sync(client, onboarded)
    assert job["status"] == "partial"
    assert "conditions failed for 1 location(s)" in job["error"]
    assert job["progress"]["orders"]["added"] == 1


def _condition(issue_id, order_id, inspections):
    item = pestpac_condition(issue_id, STORE, order_id=order_id)
    return item, pestpac_condition_detail(item, inspections=inspections, documents=[])


def test_an_orders_page_lists_what_was_logged_on_it_and_that_day(client, onboarded, pestpac):
    order_id = 1865005  # worked 2026-10-22
    pestpac.orders_by_location[STORE] = [
        pestpac_order(order_id, STORE, 180020, Posted=True, WorkDate="2026-10-22T19:00:00")
    ]
    _run_worker()  # the onboarding order sync, so the order is ours
    conditions = [
        _condition(41008, order_id, []),  # opened on the order
        _condition(41009, 1, [pestpac_inspection(order_id, "2026-10-22T19:10:00", "Still wet")]),
        _condition(41010, 1, [pestpac_inspection(2, "2026-10-22T08:00:00", "")]),  # that day
        _condition(41011, 1, [pestpac_inspection(3, "2026-09-01T08:00:00", "")]),  # neither
    ]
    pestpac.conditions_by_location[STORE] = [item for item, _ in conditions]
    for item, detail in conditions:
        pestpac.condition_details[item["IssueID"]] = detail
    pestpac.documents_by_location[STORE] = [
        pestpac_document(1, order_id=order_id, date="2026-10-01T00:00:00"),  # linked by OrderID
        pestpac_document(2, date="2026-10-22T10:00:00"),  # same day
        pestpac_document(3, date="2026-08-01T10:00:00"),  # neither
    ]
    _sync_locations(client, onboarded)

    orders = client.get(
        f"/v1/locations/{_store_id(client, onboarded)}/service-orders",
        params={"status": "all"},
        headers=onboarded["headers"],
    ).json()
    order = next(o for o in orders if o["pestpac_order_id"] == order_id)

    detail = client.get(f"/v1/service-orders/{order['id']}", headers=onboarded["headers"]).json()
    assert [c["kind"] for c in detail["trail"]] == ["operator", "company", "bill_to", "location"]
    assert detail["location_name"] and detail["invoice_id"] is None and detail["report_id"] is None

    related = client.get(
        f"/v1/service-orders/{order['id']}/related", headers=onboarded["headers"]
    ).json()
    assert [(d["pestpac_document_id"], d["link"]) for d in related["documents"]] == [
        (1, "order"),
        (2, "same_day"),
    ]
    assert {c["pestpac_issue_id"]: c["link"] for c in related["conditions"]} == {
        41008: "opened",
        41009: "inspected",
        41010: "same_day",
    }
    assert related["conditions"][-1]["link"] == "same_day"  # linked ones first
