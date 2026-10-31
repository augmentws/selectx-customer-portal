from sqlalchemy import select

from app import resync_locations
from app.db.session import SessionLocal
from app.models import Condition, LocationArea, SyncJob, SyncJobKind, SyncJobStatus
from tests.conftest import (
    pestpac_area,
    pestpac_condition,
    pestpac_condition_detail,
    pestpac_order,
)
from tests.test_documents import _sync_locations
from tests.test_notes import STORE, _store_id
from tests.test_service_orders import _run_worker, _sync

MENS_ROOM = 1322748  # the AreaID of the fixture condition


def _restroom_tree():
    return [
        pestpac_area(
            1322574,
            STORE,
            "Restrooms",
            area_type="BATHROOM",
            children=[
                pestpac_area(
                    MENS_ROOM,
                    STORE,
                    "Mens Room",
                    parent_id=1322574,
                    path="Restrooms -> Mens Room",
                    area_type="BATHROOM",
                    depth=2,
                )
            ],
        ),
        pestpac_area(1322588, STORE, "Exterior", area_type="EXTERIOR"),
    ]


def _areas():
    with SessionLocal() as db:
        rows = db.scalars(select(LocationArea).order_by(LocationArea.pestpac_area_id)).all()
        by_id = {a.id: a for a in rows}
        return {
            a.pestpac_area_id: (
                a.name,
                a.name_with_path,
                a.depth,
                by_id[a.parent_id].pestpac_area_id if a.parent_id else None,
                a.area_type,
                a.last_inspection_date,
                a.removed_at is not None,
            )
            for a in rows
        }


def _condition_area():
    with SessionLocal() as db:
        condition = db.scalar(select(Condition))
        area = (
            db.get(LocationArea, condition.location_area_id) if condition.location_area_id else None
        )
        return area.pestpac_area_id if area else None


def _open_condition(pestpac, issue_id=41008):
    item = pestpac_condition(issue_id, STORE)
    pestpac.conditions_by_location[STORE] = [item]
    pestpac.condition_details[issue_id] = pestpac_condition_detail(item)


def test_sync_location_stores_the_area_tree_and_links_conditions(client, onboarded, pestpac):
    pestpac.areas_by_location[STORE] = _restroom_tree()
    _open_condition(pestpac)
    job = _sync_locations(client, onboarded)

    assert job["status"] == "succeeded"
    assert job["progress"]["areas"] == {
        "total": 3,
        "added": 3,
        "updated": 0,
        "removed": 0,
        "conditions_linked": 1,
    }
    assert _areas() == {
        1322574: ("Restrooms", "Restrooms", 1, None, "BATHROOM", None, False),
        MENS_ROOM: ("Mens Room", "Restrooms -> Mens Room", 2, 1322574, "BATHROOM", None, False),
        1322588: ("Exterior", "Exterior", 1, None, "EXTERIOR", None, False),
    }
    assert _condition_area() == MENS_ROOM

    resp = client.get(
        f"/v1/locations/{_store_id(client, onboarded)}/areas", headers=onboarded["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert [(a["name"], a["depth"], a["open_conditions"]) for a in resp.json()] == [
        ("Exterior", 1, 0),
        ("Restrooms", 1, 0),
        ("Mens Room", 2, 1),  # under its parent
    ]

    # Next sync: PestPac dropped one area; nothing to relink.
    pestpac.areas_by_location[STORE] = _restroom_tree()[:1]
    job = _sync_locations(client, onboarded)
    assert job["progress"]["areas"]["updated"] == 2
    assert job["progress"]["areas"]["removed"] == 1
    assert job["progress"]["areas"]["conditions_linked"] == 0
    assert _areas()[1322588][-1] is True  # kept, marked removed
    assert _condition_area() == MENS_ROOM
    resp = client.get(
        f"/v1/locations/{_store_id(client, onboarded)}/areas", headers=onboarded["headers"]
    )
    assert [a["name"] for a in resp.json()] == ["Restrooms", "Mens Room"]


def test_locations_without_areas_sync_as_before(client, onboarded, pestpac):
    _open_condition(pestpac)
    job = _sync_locations(client, onboarded)
    assert job["status"] == "succeeded"
    assert job["progress"]["areas"]["total"] == 0
    assert _areas() == {}
    assert _condition_area() is None


def test_an_areas_failure_fails_only_that_location(client, onboarded, pestpac):
    pestpac.areas_by_location[STORE] = 503
    _open_condition(pestpac)
    job = _sync_locations(client, onboarded)
    assert job["status"] == "partial"
    assert [f["pestpac_location_id"] for f in job["progress"]["failed_locations"]] == [STORE]
    assert job["progress"]["locations_done"] == job["progress"]["locations_total"]


def test_an_order_sync_links_conditions_to_stored_areas(client, onboarded, pestpac):
    pestpac.areas_by_location[STORE] = _restroom_tree()
    _sync_locations(client, onboarded)  # areas stored, no conditions yet
    pestpac.orders_by_location[STORE] = [pestpac_order(1865005, STORE, 180020)]
    _open_condition(pestpac)
    job = _sync(client, onboarded)
    assert job["progress"]["conditions"]["added"] == 1
    assert _condition_area() == MENS_ROOM


def _location_sync_jobs():
    with SessionLocal() as db:
        return db.scalars(
            select(SyncJob).where(SyncJob.kind == SyncJobKind.bill_to_location_sync)
        ).all()


def test_resync_command_queues_one_location_sync_per_bill_to(
    client, world, onboarded, pestpac, caplog
):
    _run_worker()  # the onboarding sync
    caplog.set_level("INFO", logger="app.resync_locations")
    company = ["--company-id", str(world.company_a)]

    assert resync_locations.main([*company, "--dry-run"]) == 0
    assert "(dry run)" in caplog.text
    assert _location_sync_jobs() == []

    assert resync_locations.main(company) == 0
    queued = _location_sync_jobs()
    assert {j.status for j in queued} == {SyncJobStatus.queued}
    assert resync_locations.main(company) == 0  # a waiting job isn't queued twice
    assert len(_location_sync_jobs()) == len(queued)

    pestpac.areas_by_location[STORE] = _restroom_tree()
    assert resync_locations.main([*company, "--run"]) == 0
    assert {j.status for j in _location_sync_jobs()} <= {
        SyncJobStatus.succeeded,
        SyncJobStatus.partial,  # bill-tos whose fixture locations PestPac doesn't serve
    }
    assert MENS_ROOM in _areas()


def test_resync_command_needs_sync_active(world, monkeypatch, caplog):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "sync_active", False)
    assert resync_locations.main(["--company-id", str(world.company_a)]) == 1
    assert "SYNC_ACTIVE is off" in caplog.text
    assert _location_sync_jobs() == []
