from sqlalchemy import select, update

from app.db.session import SessionLocal
from app.integrations.openrouter import Usage
from app.models import AreaType, InspectionFinding, LocationArea, PestPacConnection
from app.services import inspection_findings
from tests.conftest import headers_for, pestpac_area
from tests.test_documents import _sync_locations
from tests.test_notes import STORE
from tests.test_service_reports import DRAFT


def _types():
    return [
        {"AreaTypeID": 28, "Code": "FRONTHOUSE", "Description": "Front of House"},
        {"AreaTypeID": 30, "Code": "LINEFOODPR", "Description": "Service Line/Food Prep Area"},
        {"AreaTypeID": 11, "Code": "INTERIOR", "Description": "Interior of the building"},
        {"AreaTypeID": 62, "Code": "MGBACKDOCK", "Description": "BACK DOCK"},
    ]


def _sync(client, world, headers):
    return client.post(f"/v1/operators/{world.op_a}/area-types/sync", headers=headers)


def _list(client, world, headers):
    resp = client.get(f"/v1/operators/{world.op_a}/area-types", headers=headers)
    assert resp.status_code == 200, resp.text
    return {t["code"]: (t["zone"], t["zone_name"], t["areas"]) for t in resp.json()}


def test_syncing_area_types_starts_them_with_default_zones(client, world, onboarded, pestpac):
    admin = onboarded["headers"]
    pestpac.area_types = _types()
    resp = _sync(client, world, admin)
    assert resp.status_code == 200, resp.text
    # The world already holds FRONTHOUSE (AreaTypeID 28).
    assert resp.json() == {"total": 4, "added": 3, "updated": 1, "removed": 0}
    assert _list(client, world, admin) == {
        "FRONTHOUSE": ("dining_guest", "Dining & Guest Areas", 0),
        "INTERIOR": (None, None, 0),  # generic: left unmapped
        "LINEFOODPR": ("service_line", "Service & Cook Line", 0),
        "MGBACKDOCK": ("receiving_delivery", "Receiving & Delivery", 0),
    }


def test_a_mapping_survives_the_next_sync_and_dropped_types_are_hidden(
    client, world, onboarded, pestpac
):
    admin = onboarded["headers"]
    pestpac.area_types = _types()
    _sync(client, world, admin)
    with SessionLocal() as db:
        interior = db.scalar(select(AreaType.id).where(AreaType.code == "INTERIOR"))
    resp = client.patch(f"/v1/area-types/{interior}", json={"zone": "other"}, headers=admin)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["zone"], resp.json()["zone_name"]) == ("other", "Other")

    pestpac.area_types = _types()[:3]  # PestPac dropped MGBACKDOCK
    assert _sync(client, world, admin).json() == {
        "total": 3,
        "added": 0,
        "updated": 3,
        "removed": 1,
    }
    listed = _list(client, world, admin)
    assert listed["INTERIOR"][0] == "other"
    assert "MGBACKDOCK" not in listed

    resp = client.patch(f"/v1/area-types/{interior}", json={"zone": "nowhere"}, headers=admin)
    assert resp.status_code == 422


def test_area_types_count_the_location_areas_that_carry_them(client, world, onboarded, pestpac):
    admin = onboarded["headers"]
    pestpac.area_types = _types()
    _sync(client, world, admin)
    pestpac.areas_by_location[STORE] = [
        pestpac_area(1, STORE, "Front of House", area_type="FRONTHOUSE"),
        pestpac_area(2, STORE, "Dining", area_type="FRONTHOUSE"),
        pestpac_area(3, STORE, "Main Level", area_type=None),
    ]
    _sync_locations(client, onboarded)
    assert _list(client, world, admin)["FRONTHOUSE"][2] == 2
    with SessionLocal() as db:
        assert (
            db.scalar(select(LocationArea.area_type).where(LocationArea.name == "Main Level"))
            is None
        )


def test_syncing_needs_a_verified_connection_and_reports_pestpac_failures(
    client, world, onboarded, pestpac
):
    admin = onboarded["headers"]
    pestpac.area_types = 503
    resp = _sync(client, world, admin)
    assert resp.status_code == 502
    with SessionLocal() as db:
        db.execute(update(PestPacConnection).values(status="failed"))
        db.commit()
    assert _sync(client, world, admin).status_code == 409


def test_zone_display_names_can_be_set_and_reset(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    url = f"/v1/operators/{world.op_a}/zones"
    zones = client.get(url, headers=admin).json()
    assert len(zones) == 16
    assert zones[0] == {
        "zone": "exterior_perimeter",
        "display_name": "Exterior Perimeter",
        "default_name": "Exterior Perimeter",
    }

    resp = client.put(
        f"{url}/dining_guest", json={"display_name": " Front of House "}, headers=admin
    )
    assert resp.status_code == 200, resp.text
    named = {z["zone"]: z["display_name"] for z in resp.json()}
    assert named["dining_guest"] == "Front of House"

    resp = client.put(f"{url}/dining_guest", json={"display_name": ""}, headers=admin)
    assert {z["zone"]: z["display_name"] for z in resp.json()}["dining_guest"] == (
        "Dining & Guest Areas"
    )
    assert client.put(f"{url}/nowhere", json={}, headers=admin).status_code == 422


def test_findings_store_zones_and_the_order_shows_their_display_names(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    client.put(
        f"/v1/operators/{world.op_a}/zones/dumpster_waste",
        json={"display_name": "Rear Entry & Trash Room"},
        headers=admin,
    )
    with SessionLocal() as db:
        inspection_findings.save(
            db,
            operator_id=world.op_a,
            service_order_id=world.service_order_a,
            location_id=world.location_a,
            report_id=None,
            source="extraction",
            findings=inspection_findings.FindingsOut.model_validate(DRAFT["findings"]),
            model="test/model",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2, cost=0.0),
        )
        db.commit()
        finding = db.scalar(select(InspectionFinding))
        assert finding.activity_locations == ["trash room wall"]
        assert finding.activity_zones == ["dumpster_waste"]
        assert [(i.kind, i.zone) for i in finding.items] == [
            ("structural", "dumpster_waste"),
            ("pest", "dishwashing_drains"),
        ]

    order = client.get(f"/v1/service-orders/{world.service_order_a}", headers=admin).json()
    assert order["findings"]["activity_zone_names"] == ["Rear Entry & Trash Room"]
    assert [(i["zone"], i["zone_name"]) for i in order["findings"]["items"]] == [
        ("dumpster_waste", "Rear Entry & Trash Room"),
        ("dishwashing_drains", "Dishwashing & Drains"),
    ]
