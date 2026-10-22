import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import worker
from app.db.session import SessionLocal
from app.models import (
    ConnectionStatus,
    PestPacConnection,
    ServiceOrder,
    SyncJob,
    SyncJobStatus,
    Technician,
)
from app.services import sync_jobs
from tests.conftest import pestpac_order

BILL_TO = 180020  # onboarded by `onboarded` below; locations 900001-900003 from the fixture
OTHER_BILL_TO = 555555  # never onboarded


def _run_worker():
    worker._Stop.requested = False
    return worker.run_pending()


def _orders(client, onboarded, status="open"):
    resp = client.get(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/service-orders",
        params={"status": status},
        headers=onboarded["headers"],
    )
    assert resp.status_code == 200
    return resp.json()


def _latest_job(client, onboarded):
    return client.get(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/sync-jobs", headers=onboarded["headers"]
    ).json()[0]


def _sync(client, onboarded):
    resp = client.post(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/service-orders/sync",
        headers=onboarded["headers"],
    )
    assert resp.status_code == 202
    _run_worker()
    return _latest_job(client, onboarded)


def test_onboarding_queues_a_sync(client, onboarded):
    job = _latest_job(client, onboarded)
    assert job["kind"] == "bill_to_service_orders"
    assert job["status"] == "queued"


def test_sync_stores_agreed_fields_only(client, onboarded, pestpac):
    pestpac.orders_by_location[900001] = [pestpac_order(1854693, 900001, BILL_TO)]
    assert _run_worker() == 1

    job = _latest_job(client, onboarded)
    assert job["status"] == "succeeded"
    assert job["progress"]["locations_total"] == 3
    assert job["progress"]["orders"]["added"] == 1

    rows = _orders(client, onboarded)
    assert len(rows) == 1
    order = rows[0]
    assert order["pestpac_order_id"] == 1854693
    assert order["order_number"] == "2639111"
    assert order["service_code"] == "RAMP MONITOR"
    assert order["description"] == "RAMP MONITORING PROGRAM"
    assert order["work_date"] == "2026-10-19T14:00:00"
    assert order["tech_name"] == "TECH01"
    assert order["tech_id"] == 1332
    assert order["location_instructions"] == "Enter through the rear door."
    assert order["service_instructions"].startswith("Perform a full inspection")
    assert order["order_instructions"] is None
    assert order["posted"] is False and order["posted_at"] is None
    assert order["location_id"] is not None

    resp_text = str(rows)
    for leaked in ("201.42", "SubTotal", "TaxDetails", "R76", "Production"):
        assert leaked not in resp_text


def test_orders_for_other_bill_tos_are_skipped(client, onboarded, pestpac):
    pestpac.orders_by_location[900001] = [
        pestpac_order(1, 900001, BILL_TO),
        pestpac_order(2, 900001, OTHER_BILL_TO),
    ]
    _run_worker()
    assert [o["pestpac_order_id"] for o in _orders(client, onboarded)] == [1]
    assert _latest_job(client, onboarded)["progress"]["orders"]["skipped_other_bill_to"] == 1


def test_posted_flip_records_when_it_was_worked(client, onboarded, pestpac):
    pestpac.orders_by_location[900001] = [pestpac_order(1, 900001, BILL_TO, Posted=False)]
    _run_worker()

    pestpac.orders_by_location[900001] = [pestpac_order(1, 900001, BILL_TO, Posted=True)]
    job = _sync(client, onboarded)
    assert job["progress"]["orders"]["newly_posted"] == 1
    first = _orders(client, onboarded)[0]
    assert first["posted"] is True and first["posted_at"] is not None

    # Still posted on the next sync: the original posted_at is kept.
    job = _sync(client, onboarded)
    assert job["progress"]["orders"]["newly_posted"] == 0
    assert _orders(client, onboarded)[0]["posted_at"] == first["posted_at"]


def test_billed_orders_are_closed_and_kept(client, onboarded, pestpac):
    pestpac.orders_by_location[900001] = [
        pestpac_order(1, 900001, BILL_TO, Posted=True),
        pestpac_order(2, 900001, BILL_TO),
    ]
    _run_worker()

    pestpac.orders_by_location[900001] = [pestpac_order(2, 900001, BILL_TO)]  # 1 was billed
    job = _sync(client, onboarded)
    assert job["progress"]["orders"]["closed"] == 1
    assert [o["pestpac_order_id"] for o in _orders(client, onboarded)] == [2]
    closed = _orders(client, onboarded, status="closed")
    assert [o["pestpac_order_id"] for o in closed] == [1]
    assert closed[0]["closed_at"] is not None
    assert closed[0]["service_code"] == "RAMP MONITOR"  # our copy survives billing

    pestpac.orders_by_location[900001] = [
        pestpac_order(1, 900001, BILL_TO, Posted=True),
        pestpac_order(2, 900001, BILL_TO),
    ]
    job = _sync(client, onboarded)
    assert job["progress"]["orders"]["reopened"] == 1
    assert len(_orders(client, onboarded)) == 2


def test_one_failing_location_gives_a_partial_job(client, onboarded, pestpac):
    pestpac.orders_by_location[900001] = [pestpac_order(1, 900001, BILL_TO)]
    pestpac.orders_by_location[900002] = 500
    _run_worker()
    job = _latest_job(client, onboarded)
    assert job["status"] == "partial"
    assert [f["pestpac_location_id"] for f in job["progress"]["failed_locations"]] == [900002]
    assert len(_orders(client, onboarded)) == 1  # the other locations still synced


def test_location_404_is_a_failure_not_an_empty_list(client, onboarded, pestpac):
    pestpac.orders_by_location[900001] = [pestpac_order(1, 900001, BILL_TO)]
    _run_worker()
    pestpac.orders_by_location[900001] = 404
    job = _sync(client, onboarded)
    assert job["status"] == "partial"
    assert len(_orders(client, onboarded)) == 1  # not closed


def test_every_location_failing_fails_the_job(client, onboarded, pestpac):
    for location_id in (900001, 900002, 900003):
        pestpac.orders_by_location[location_id] = 503
    _run_worker()
    assert _latest_job(client, onboarded)["status"] == "failed"


def test_unverified_connection_fails_the_job(client, onboarded, world):
    with SessionLocal() as db:
        db.get(PestPacConnection, world.op_a).status = ConnectionStatus.failed
        db.commit()
    _run_worker()
    job = _latest_job(client, onboarded)
    assert job["status"] == "failed"
    assert "PestPac API access" in job["error"]


def test_sync_requests_while_active_return_the_same_job(client, onboarded):
    url = f"/v1/bill-tos/{onboarded['bill_to_id']}/service-orders/sync"
    first = client.post(url, headers=onboarded["headers"]).json()
    second = client.post(url, headers=onboarded["headers"]).json()
    assert first["id"] == second["id"]


def test_location_sync(client, onboarded, pestpac):
    _run_worker()  # drain the onboarding job
    locations = client.get(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/locations", headers=onboarded["headers"]
    ).json()
    store = next(loc for loc in locations if loc["pestpac_location_id"] == 900002)
    pestpac.orders_by_location[900002] = [pestpac_order(7, 900002, BILL_TO)]

    resp = client.post(
        f"/v1/locations/{store['id']}/service-orders/sync", headers=onboarded["headers"]
    )
    assert resp.status_code == 202
    assert resp.json()["kind"] == "location_service_orders"
    _run_worker()

    job = client.get(f"/v1/sync-jobs/{resp.json()['id']}", headers=onboarded["headers"]).json()
    assert job["status"] == "succeeded"
    assert job["progress"]["locations_total"] == 1
    orders = client.get(
        f"/v1/locations/{store['id']}/service-orders", headers=onboarded["headers"]
    ).json()
    assert [o["pestpac_order_id"] for o in orders] == [7]

    locations = client.get(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/locations", headers=onboarded["headers"]
    ).json()
    assert next(loc for loc in locations if loc["id"] == store["id"])["open_order_count"] == 1


def test_order_listed_under_the_wrong_location_fails_that_location(client, onboarded, pestpac):
    # PestPac lists it under 900001 but says it belongs to 999999: rejected as inconsistent.
    pestpac.orders_by_location[900001] = [pestpac_order(1, 999999, BILL_TO)]
    _run_worker()
    assert _latest_job(client, onboarded)["status"] == "partial"


def test_stale_running_job_is_retried_then_given_up(client, onboarded, pestpac):
    with SessionLocal() as db:
        job = db.scalar(select(SyncJob))
        job.status = SyncJobStatus.running
        job.attempts = 1
        job.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
        job_id = job.id

    _run_worker()
    with SessionLocal() as db:
        job = db.get(SyncJob, job_id)
        assert job.status == SyncJobStatus.succeeded
        assert job.attempts == 2

        job.status = SyncJobStatus.running
        job.attempts = 3
        job.heartbeat_at = datetime.now(UTC) - timedelta(hours=1)
        db.commit()
    _run_worker()
    with SessionLocal() as db:
        job = db.get(SyncJob, job_id)
        assert job.status == SyncJobStatus.failed
        assert "Gave up" in job.error


def test_fresh_running_job_is_not_claimed_twice(onboarded):
    with SessionLocal() as db:
        claimed = sync_jobs.claim_next(db)
        assert claimed is not None
    with SessionLocal() as db:
        assert sync_jobs.claim_next(db) is None


def test_service_orders_are_never_deleted(client, onboarded, pestpac):
    pestpac.orders_by_location[900001] = [pestpac_order(1, 900001, BILL_TO)]
    _run_worker()
    pestpac.orders_by_location[900001] = []
    _sync(client, onboarded)
    with SessionLocal() as db:
        assert db.scalar(select(ServiceOrder).where(ServiceOrder.pestpac_order_id == 1))


def _technician_lookups(pestpac) -> int:
    """Single-technician lookups (not the seeding list call)."""
    return sum(
        re.search(r"/lookups/Employees/technicians/\d+", c.request.url) is not None
        for c in pestpac.calls
    )


def test_technicians_are_seeded_up_front(client, onboarded, pestpac):
    pestpac.orders_by_location[900001] = [
        pestpac_order(1, 900001, BILL_TO),
        pestpac_order(2, 900001, BILL_TO),
    ]
    _run_worker()

    job = _latest_job(client, onboarded)
    assert job["progress"]["technicians"] == {"total": 1, "added": 1, "updated": 0}
    assert _technician_lookups(pestpac) == 0  # linked from the seeded table
    orders = _orders(client, onboarded)
    assert {o["technician_name"] for o in orders} == {"Pat Tech"}


def test_tech_missing_from_the_list_is_looked_up_once(client, onboarded, pestpac):
    pestpac.technicians_listed = []  # e.g. hired after the list was cached by PestPac
    pestpac.orders_by_location[900001] = [
        pestpac_order(1, 900001, BILL_TO),
        pestpac_order(2, 900001, BILL_TO),
    ]
    pestpac.orders_by_location[900002] = [pestpac_order(3, 900002, BILL_TO)]
    _run_worker()

    job = _latest_job(client, onboarded)
    assert job["progress"]["orders"]["technicians_resolved"] == 1
    assert _technician_lookups(pestpac) == 1  # three orders, one tech, one lookup
    assert {o["technician_name"] for o in _orders(client, onboarded)} == {"Pat Tech"}

    _sync(client, onboarded)  # known now: no new lookup
    assert _technician_lookups(pestpac) == 1


def test_unresolved_technician_falls_back_and_is_retried(client, onboarded, pestpac):
    tech = pestpac.technicians.pop(1332)
    pestpac.technicians_listed = []
    pestpac.orders_by_location[900001] = [pestpac_order(1, 900001, BILL_TO)]
    _run_worker()

    job = _latest_job(client, onboarded)
    assert job["status"] == "succeeded"  # a missing tech never fails the sync
    assert job["progress"]["orders"]["technicians_unresolved"] == 1
    order = _orders(client, onboarded)[0]
    assert order["technician_id"] is None
    assert order["technician_name"] == "TECH01"  # PestPac's Tech1

    pestpac.technicians[1332] = tech
    pestpac.technicians_listed = None
    _sync(client, onboarded)
    assert _orders(client, onboarded)[0]["technician_name"] == "Pat Tech"


def test_technician_personal_data_is_not_stored(client, onboarded, pestpac):
    pestpac.orders_by_location[900001] = [pestpac_order(1, 900001, BILL_TO)]
    _run_worker()
    with SessionLocal() as db:
        tech = db.scalar(select(Technician))
        stored = {c.name: getattr(tech, c.name) for c in Technician.__table__.columns}
    assert stored["pestpac_tech_id"] == 1332
    assert stored["pestpac_employee_id"] == 2325
    assert stored["username"] == "TECH01"
    text = str(stored) + str(_orders(client, onboarded))
    for leaked in ("tech.one@personal.example", "555-010-0199", "EMERGENCY PERSON", "1900-01-01"):
        assert leaked not in text
