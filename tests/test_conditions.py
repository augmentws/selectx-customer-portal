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
    _open_condition(pestpac)
    _run_worker()  # the onboarding order sync, so the condition's order is ours
    job = _sync_locations(client, onboarded)

    assert job["status"] == "succeeded"
    assert job["progress"]["conditions"]["added"] == 1
    assert job["progress"]["conditions"]["details_fetched"] == 1
    assert job["progress"]["conditions"]["documents_linked"] == 1
    assert any(
        c.request.url.endswith(f"/Locations/{STORE}/conditions?status=Open") for c in pestpac.calls
    )

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


def test_order_syncs_leave_conditions_alone(client, onboarded, pestpac):
    _open_condition(pestpac)
    _sync(client, onboarded)
    assert not any("/conditions" in c.request.url for c in pestpac.calls)
