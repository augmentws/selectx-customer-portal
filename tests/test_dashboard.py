from datetime import UTC, datetime

import pytest

from app.db.session import SessionLocal
from app.models import BillTo, Location, ServiceOrder, Technician
from app.services.dashboard import store_number
from tests.conftest import headers_for


def _order(world, location_id, order_id, *, work_date=None, posted=True, closed=False, **extra):
    return ServiceOrder(
        operator_id=world.op_a,
        bill_to_id=extra.pop("bill_to_id", world.bill_to_a),
        location_id=location_id,
        pestpac_order_id=order_id,
        pestpac_location_id=800001,
        work_date=work_date,
        posted=posted,
        closed_at=datetime.now(UTC) if closed else None,
        pestpac_fetched_at=datetime.now(UTC),
        **extra,
    )


@pytest.fixture
def activity(world):
    """Location A: the world's open order plus four worked ones over three months (two techs,
    one resolved, one raw). A second location with no orders, and one removed location."""
    with SessionLocal() as db:
        tech = Technician(
            operator_id=world.op_a,
            pestpac_tech_id=1332,
            username="PTECH",
            first_name="Pat",
            last_name="Tech",
            active=True,
            pestpac_fetched_at=datetime.now(UTC),
        )
        db.add(tech)
        db.flush()
        quiet = Location(
            operator_id=world.op_a,
            bill_to_id=world.bill_to_a,
            pestpac_location_id=800002,
            pestpac_company="ACME TACOS - STORE #2",
            pestpac_active=True,
            pestpac_fetched_at=datetime.now(UTC),
        )
        gone = Location(
            operator_id=world.op_a,
            bill_to_id=world.bill_to_a,
            pestpac_location_id=800003,
            pestpac_company="ACME TACOS - STORE #3",
            pestpac_active=True,
            removed_at=datetime.now(UTC),
            pestpac_fetched_at=datetime.now(UTC),
        )
        db.add_all([quiet, gone])
        a = world.location_a
        db.add_all(
            [
                _order(world, a, 1, work_date=datetime(2026, 1, 5, 9), service_code="RAMP 1",
                       technician_id=tech.id, tech_name="PTECH", closed=True),
                _order(world, a, 2, work_date=datetime(2026, 1, 20, 9), service_code="RAMP MONITOR",
                       technician_id=tech.id, tech_name="PTECH", closed=True),
                _order(world, a, 3, work_date=datetime(2026, 3, 2, 9), service_code="RAMP MONITOR",
                       tech_name="OTHER-1"),
                _order(world, a, 4, work_date=datetime(2026, 3, 30, 9), service_code="RAMP MONITOR",
                       technician_id=tech.id, tech_name="PTECH"),
                # Closed without being worked: not a service.
                _order(world, a, 5, work_date=datetime(2026, 2, 1, 9), posted=False, closed=True),
            ]
        )  # fmt: skip
        db.commit()
        return {"quiet": quiet.id, "gone": gone.id}


def _dashboard(client, world, **params):
    admin = headers_for(client, world.emails["admin_a"])
    resp = client.get(f"/v1/companies/{world.company_a}/dashboard", params=params, headers=admin)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_headline_counts(client, world, activity):
    h = _dashboard(client, world)["headline"]
    assert h["locations"] == 2  # the removed location isn't listed
    assert h["locations_serviced"] == 1
    assert h["services"] == 4
    assert h["open_orders"] == 1  # the world's order
    assert (h["awaiting_billing"], h["billed"]) == (2, 2)
    assert h["technicians"] == 2
    assert h["first_service"].startswith("2026-01-05T09:00")
    assert h["last_service"].startswith("2026-03-30T09:00")


def test_services_by_month_fill_gaps(client, world, activity):
    months = _dashboard(client, world)["services_by_month"]
    assert months == [
        {"month": "2026-01", "services": 2},
        {"month": "2026-02", "services": 0},
        {"month": "2026-03", "services": 2},
    ]


def test_services_by_code_and_technician(client, world, activity):
    d = _dashboard(client, world)
    assert d["services_by_code"] == [
        {"service_code": "RAMP MONITOR", "services": 3},
        {"service_code": "RAMP 1", "services": 1},
    ]
    assert [(t["name"], t["services"]) for t in d["top_technicians"]] == [
        ("Pat Tech", 3),
        ("OTHER-1", 1),
    ]


def test_store_rows(client, world, activity):
    stores = {s["pestpac_location_id"]: s for s in _dashboard(client, world)["stores"]}
    assert set(stores) == {800001, 800002}
    busy, quiet = stores[800001], stores[800002]
    assert (busy["services"], busy["open_orders"], busy["store_number"]) == (4, 1, "1")
    assert busy["last_service"].startswith("2026-03-30")
    assert (quiet["services"], quiet["last_service"], quiet["store_number"]) == (0, None, "2")


def test_bill_to_filter(client, world, activity):
    with SessionLocal() as db:
        other = BillTo(
            operator_id=world.op_a,
            company_id=world.company_a,
            pestpac_bill_to_id=175999,
            name="Acme West",
        )
        db.add(other)
        db.commit()
        other_id = other.id
    d = _dashboard(client, world, bill_to_id=str(other_id))
    assert d["bill_to_id"] == str(other_id)
    assert d["headline"]["services"] == 0 and d["stores"] == []
    assert _dashboard(client, world, bill_to_id=str(world.bill_to_a))["headline"]["services"] == 4


def test_bill_to_of_another_company_is_404(client, world):
    admin = headers_for(client, world.emails["platform_admin"])
    with SessionLocal() as db:
        foreign = BillTo(
            operator_id=world.op_b,
            company_id=world.company_b,
            pestpac_bill_to_id=220001,
            name="Beta HQ",
        )
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id
    resp = client.get(
        f"/v1/companies/{world.company_a}/dashboard",
        params={"bill_to_id": str(foreign_id)},
        headers=admin,
    )
    assert resp.status_code == 404


def test_empty_company(client, world):
    admin = headers_for(client, world.emails["admin_b"])
    resp = client.get(f"/v1/companies/{world.company_b}/dashboard", headers=admin)
    body = resp.json()
    assert body["headline"]["services"] == 0
    assert body["services_by_month"] == [] and body["stores"] == []


@pytest.mark.parametrize(
    ("name", "number"),
    [("CHIPOTLE - STORE #2301", "2301"), ("Store # 12", "12"), ("No number", None), (None, None)],
)
def test_store_number(name, number):
    assert store_number(name) == number
