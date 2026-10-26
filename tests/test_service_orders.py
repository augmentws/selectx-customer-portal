import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app import worker
from app.db.session import SessionLocal
from app.models import (
    ConnectionStatus,
    Location,
    PestPacConnection,
    ServiceOrder,
    SyncJob,
    SyncJobKind,
    SyncJobStatus,
    Technician,
    Tenant,
)
from app.services import sync_jobs
from tests.conftest import headers_for, pestpac_order

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
    assert order["technician_comment"] is None  # "" in the fixture
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

    pestpac.orders_by_location[900001] = [
        pestpac_order(1, 900001, BILL_TO, Posted=True, TechnicianComment=" Sealed gap by door. ")
    ]
    job = _sync(client, onboarded)
    assert job["progress"]["orders"]["newly_posted"] == 1
    first = _orders(client, onboarded)[0]
    assert first["posted"] is True and first["posted_at"] is not None
    assert first["technician_comment"] == "Sealed gap by door."

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


def test_location_orders_are_listed_oldest_first(client, onboarded, pestpac):
    _run_worker()  # drain the onboarding job
    locations = client.get(
        f"/v1/bill-tos/{onboarded['bill_to_id']}/locations", headers=onboarded["headers"]
    ).json()
    store = next(loc for loc in locations if loc["pestpac_location_id"] == 900002)
    pestpac.orders_by_location[900002] = [
        pestpac_order(1, 900002, BILL_TO, WorkDate="2026-10-19T14:00:00"),
        pestpac_order(2, 900002, BILL_TO, WorkDate=None),
        pestpac_order(3, 900002, BILL_TO, WorkDate="2026-09-01T09:00:00"),
    ]
    client.post(f"/v1/locations/{store['id']}/service-orders/sync", headers=onboarded["headers"])
    _run_worker()

    orders = client.get(
        f"/v1/locations/{store['id']}/service-orders", headers=onboarded["headers"]
    ).json()
    assert [o["pestpac_order_id"] for o in orders] == [3, 1, 2]
    # Bill-to lists stay newest first.
    assert [o["pestpac_order_id"] for o in _orders(client, onboarded)] == [1, 3, 2]


def test_posted_orders_are_listed_oldest_first_and_paged(client, onboarded, pestpac):
    _run_worker()  # drain the onboarding job
    pestpac.orders_by_location[900001] = [
        pestpac_order(1, 900001, BILL_TO, Posted=True, WorkDate="2026-10-19T14:00:00"),
        pestpac_order(2, 900001, BILL_TO, Posted=False, WorkDate="2026-08-01T09:00:00"),
    ]
    pestpac.orders_by_location[900002] = [
        pestpac_order(3, 900002, BILL_TO, Posted=True, WorkDate="2026-09-01T09:00:00"),
        pestpac_order(4, 900002, BILL_TO, Posted=True, WorkDate="2026-10-01T09:00:00"),
    ]
    _sync(client, onboarded)
    pestpac.orders_by_location[900002] = []  # order 3 and 4 billed: still listed as posted
    _sync(client, onboarded)

    company_id = client.get(
        f"/v1/bill-tos/{onboarded['bill_to_id']}", headers=onboarded["headers"]
    ).json()["company_id"]
    for path in (
        f"/v1/bill-tos/{onboarded['bill_to_id']}/posted-service-orders",
        f"/v1/companies/{company_id}/posted-service-orders",
    ):
        page = client.get(path, headers=onboarded["headers"]).json()
        assert page["total"] == 3
        assert [o["pestpac_order_id"] for o in page["items"]] == [3, 4, 1]
        assert page["items"][0]["location_name"] is not None
        assert page["items"][0]["report_id"] is None
        assert page["items"][0]["closed_at"] is not None

        page = client.get(
            path, params={"limit": 2, "offset": 2}, headers=onboarded["headers"]
        ).json()
        assert [o["pestpac_order_id"] for o in page["items"]] == [1]


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


def test_location_sync_status_is_not_crowded_out_by_other_locations(client, onboarded):
    """Webhooks queue many syncs for other locations; a location still sees its newest job of
    each kind (its own or bill-to-wide)."""
    now = datetime.now(UTC)
    with SessionLocal() as db:
        locations = {
            loc.pestpac_location_id: loc
            for loc in db.scalars(
                select(Location).where(Location.bill_to_id == onboarded["bill_to_id"])
            )
        }
        mine, other = locations[900001], locations[900002]
        # The onboarding job is older than all of these.
        db.execute(
            SyncJob.__table__.update()
            .where(SyncJob.bill_to_id == mine.bill_to_id)
            .values(created_at=now - timedelta(days=2))
        )

        def job(kind, location, age):
            row = SyncJob(
                operator_id=mine.operator_id,
                kind=kind,
                status=SyncJobStatus.succeeded,
                bill_to_id=mine.bill_to_id,
                location_id=location.id if location else None,
                created_at=now - age,
            )
            db.add(row)
            return row

        old_orders = job(SyncJobKind.location_service_orders, mine, timedelta(hours=5))
        orders = job(SyncJobKind.location_service_orders, mine, timedelta(hours=4))
        documents = job(SyncJobKind.bill_to_location_sync, None, timedelta(hours=3))
        for n in range(15):
            job(SyncJobKind.location_service_orders, other, timedelta(minutes=n))
        db.commit()
        expected = [documents.id, orders.id]
        assert old_orders.id not in expected

    url = f"/v1/bill-tos/{onboarded['bill_to_id']}/sync-jobs"
    crowded = client.get(url, headers=onboarded["headers"]).json()
    assert all(j["location_id"] == str(other.id) for j in crowded)
    resp = client.get(url, params={"location_id": str(mine.id)}, headers=onboarded["headers"])
    assert resp.status_code == 200
    # Newest of each kind: these two and the onboarding job (bill-to-wide, orders).
    ids = [j["id"] for j in resp.json()]
    assert ids[:2] == [str(i) for i in expected]
    assert len(ids) == 3


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


def test_locations_report_open_worked_and_last_service(client, world):
    """The bill-to's locations table shows how many orders are open, how many are worked and
    awaiting billing, and when the store was last serviced (billed or not)."""
    with SessionLocal() as db:

        def order(pestpac_order_id: int, *, posted: bool, closed: bool, day: int) -> ServiceOrder:
            return ServiceOrder(
                operator_id=world.op_a,
                bill_to_id=world.bill_to_a,
                location_id=world.location_a,
                pestpac_order_id=pestpac_order_id,
                pestpac_location_id=800001,
                work_date=datetime(2026, 10, day, 9, 0),
                posted=posted,
                closed_at=datetime.now(UTC) if closed else None,
                pestpac_fetched_at=datetime.now(UTC),
            )

        db.add_all(
            [
                order(710001, posted=True, closed=False, day=20),
                order(710002, posted=True, closed=True, day=22),  # billed: newest service
                order(710003, posted=False, closed=False, day=24),  # scheduled, not worked
            ]
        )
        db.commit()

    headers = headers_for(client, world.emails["staff_a"])
    listed = client.get(f"/v1/bill-tos/{world.bill_to_a}/locations", headers=headers).json()
    detail = client.get(f"/v1/locations/{world.location_a}", headers=headers).json()
    for loc in (next(x for x in listed if x["id"] == str(world.location_a)), detail):
        # service_order_a (open) plus 710001 and 710003; the world's reported orders are billed.
        assert loc["open_order_count"] == 3
        assert loc["worked_order_count"] == 1
        assert loc["last_service_at"] == "2026-10-22T09:00:00"


def test_posted_orders_filter_by_search_technician_and_service_code(client, world):
    with SessionLocal() as db:
        store = Location(
            operator_id=world.op_a,
            bill_to_id=world.bill_to_a,
            pestpac_location_id=800077,
            pestpac_company="ACME TACOS - STORE #77",
            pestpac_active=True,
            pestpac_fetched_at=datetime.now(UTC),
        )
        pat = Technician(
            operator_id=world.op_a,
            pestpac_tech_id=61,
            first_name="Pat",
            last_name="Tester",
            pestpac_fetched_at=datetime.now(UTC),
        )
        db.add_all([store, pat])
        db.flush()

        def worked(order_id: int, location_id, *, code: str, tech=None) -> ServiceOrder:
            return ServiceOrder(
                operator_id=world.op_a,
                bill_to_id=world.bill_to_a,
                location_id=location_id,
                pestpac_order_id=order_id,
                pestpac_location_id=800001,
                order_number=f"N{order_id}",
                service_code=code,
                technician_id=tech,
                work_date=datetime(2026, 10, 1, 9, 0) + timedelta(days=order_id - 720000),
                posted=True,
                pestpac_fetched_at=datetime.now(UTC),
            )

        db.add_all(
            [
                worked(720001, world.location_a, code="RAMP MONITOR", tech=pat.id),
                worked(720002, store.id, code="RAMP MONITOR"),
                worked(720003, store.id, code="RCOMMERCIAL", tech=pat.id),
            ]
        )
        db.commit()
        pat_id = str(pat.id)

    headers = headers_for(client, world.emails["staff_a"])

    def ids(**params) -> list[int]:
        for scope in (f"/v1/bill-tos/{world.bill_to_a}", f"/v1/companies/{world.company_a}"):
            page = client.get(f"{scope}/posted-service-orders", params=params, headers=headers)
            assert page.status_code == 200, page.text
            body = page.json()
            assert body["total"] == len(body["items"])
            found = [o["pestpac_order_id"] for o in body["items"]]
        return found

    assert ids() == [720001, 720002, 720003]
    assert ids(q="store #77") == [720002, 720003]  # the location's name, anywhere
    assert ids(q="N720003") == [720003]  # order number, exactly
    assert ids(q="720001") == [720001]  # OrderID
    assert ids(q="72000") == []
    assert ids(technician_id=pat_id) == [720001, 720003]
    assert ids(service_code="RAMP MONITOR") == [720001, 720002]
    assert ids(technician_id=pat_id, service_code="RCOMMERCIAL", q="#77") == [720003]

    # The choices cover every posted order, whatever the filters.
    page = client.get(
        f"/v1/bill-tos/{world.bill_to_a}/posted-service-orders",
        params={"q": "nothing matches"},
        headers=headers,
    ).json()
    assert page["total"] == 0
    assert page["technicians"] == [{"id": pat_id, "name": "Pat Tester"}]
    assert page["service_codes"] == ["RAMP MONITOR", "RCOMMERCIAL"]


def test_technician_stored_meanwhile_by_another_worker_is_used(client, onboarded, pestpac):
    """Two workers can resolve the same new TechID at once: the later insert gives way to the
    stored row instead of failing the job or webhook event."""
    from app.schemas.pestpac import ServiceOrderSyncCounts
    from app.services import pestpac_connection
    from app.services.technicians import TechnicianResolver
    from tests.conftest import TECHNICIAN_FIXTURE

    tech_id = TECHNICIAN_FIXTURE["TechID"]
    with SessionLocal() as db:
        operator_id = db.scalar(select(PestPacConnection.operator_id))
        client_ = pestpac_connection.get_pestpac_client(db, db.get(Tenant, operator_id))
        first = TechnicianResolver(db, client_, operator_id).resolve(
            tech_id, ServiceOrderSyncCounts()
        )
        db.commit()

        # The other worker's lookup ran before that commit, so it saw no technician.
        resolver = TechnicianResolver(db, client_, operator_id)
        real_scalar = db.scalar
        calls = {"n": 0}

        def scalar_missing_once(statement, *args, **kwargs):
            calls["n"] += 1
            return None if calls["n"] == 1 else real_scalar(statement, *args, **kwargs)

        db.scalar = scalar_missing_once
        try:
            again = resolver.resolve(tech_id, ServiceOrderSyncCounts())
        finally:
            del db.scalar
        db.commit()
        assert again == first
        count = db.scalar(
            select(func.count())
            .select_from(Technician)
            .where(Technician.pestpac_tech_id == tech_id)
        )
        assert count == 1
