import json

import pytest
import responses
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import BillTo, Location
from tests.conftest import (
    LOCATIONS_FIXTURE,
    LOCATIONS_URL,
    PESTPAC_BASE,
    PESTPAC_TOKEN_URL,
    headers_for,
    locations_callback,
    pestpac_bill_to_body,
    pestpac_locations,
)

DROPPED = ("PAT", "TESTER", "INSPECTOR PERSON", "UserDefinedFields", "SmsMarketing")


@pytest.fixture
def page_size(monkeypatch):
    def use(size: int, max_pages: int = 200):
        monkeypatch.setenv("PESTPAC_PAGE_SIZE", str(size))
        monkeypatch.setenv("PESTPAC_MAX_PAGES", str(max_pages))
        get_settings.cache_clear()

    yield use
    monkeypatch.undo()
    get_settings.cache_clear()


def _onboard(client, headers, company_id, bill_to_id=180020):
    return client.post(
        f"/v1/companies/{company_id}/bill-tos",
        json={"pestpac_bill_to_id": bill_to_id},
        headers=headers,
    )


def _mock(rsps, bill_to_id: int, items: list[dict] | None = None):
    """PestPac for one bill-to: token, the bill-to, and its (paged) locations."""
    rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
    rsps.get(
        f"{PESTPAC_BASE}/BillTos/{bill_to_id}", body=json.dumps(pestpac_bill_to_body(bill_to_id))
    )
    rsps.add_callback(
        responses.GET,
        LOCATIONS_URL,
        locations_callback({bill_to_id: pestpac_locations(bill_to_id, items)}),
    )


def test_onboarding_syncs_locations(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    resp = _onboard(client, admin, world.company_a)
    assert resp.status_code == 201
    body = resp.json()
    assert body["locations_sync"] == {"total": 3, "added": 3, "updated": 0, "removed": 0}
    assert body["location_count"] == 3

    locations = client.get(f"/v1/bill-tos/{body['id']}/locations", headers=admin)
    assert locations.status_code == 200
    rows = locations.json()
    assert [r["pestpac_company"] for r in rows] == [
        "ACME TACOS - STORE #2301",
        "ACME TACOS - STORE #4200",
        "ACME TACOS - STORE #436",
    ]
    store = next(r for r in rows if r["pestpac_location_id"] == 900001)
    assert store["pestpac_location_code"] == "491257"
    assert store["email"] == "manager.one@acme-tacos.example"
    assert store["phone"] == "555-010-0100"
    assert store["account_type"] == "Commercial"
    assert store["pestpac_type"] == "ENTERPRISE"
    assert store["latitude"] == pytest.approx(40.75232)
    assert store["longitude"] == pytest.approx(-73.974099)
    assert store["zip"] == "10017"
    inactive = next(r for r in rows if r["pestpac_location_id"] == 900003)
    assert inactive["pestpac_active"] is False
    for value in DROPPED:
        assert value not in locations.text


@pytest.mark.parametrize(
    ("size", "pages_requested"),
    [
        (2, 2),  # 2 + 1: the short second page ends it
        (3, 2),  # exactly full first page, then an empty one
        (50, 1),
    ],
)
def test_paging(client, world, page_size, size, pages_requested):
    page_size(size)
    admin = headers_for(client, world.emails["admin_a"])
    with responses.RequestsMock() as rsps:
        _mock(rsps, 180020)
        resp = _onboard(client, admin, world.company_a)
        location_calls = [c for c in rsps.calls if "/locations/pageable" in c.request.url]
    assert resp.status_code == 201
    assert resp.json()["locations_sync"]["total"] == 3
    assert len(location_calls) == pages_requested
    assert f"take={size}" in location_calls[0].request.url


def test_bill_to_without_locations(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    with responses.RequestsMock() as rsps:
        _mock(rsps, 180020, items=[])
        resp = _onboard(client, admin, world.company_a)
    assert resp.json()["locations_sync"] == {"total": 0, "added": 0, "updated": 0, "removed": 0}


def test_refresh_adds_updates_and_removes(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    bill_to_id = _onboard(client, admin, world.company_a).json()["id"]

    changed = [dict(LOCATIONS_FIXTURE[0], Company="ACME TACOS - STORE #436 (RENAMED)")]
    changed.append(LOCATIONS_FIXTURE[1])
    changed.append(dict(LOCATIONS_FIXTURE[1], LocationID=900004, Company="ACME TACOS - NEW"))
    # The cached client reuses its token, so no token call is guaranteed.
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, 180020, items=changed)
        resp = client.post(f"/v1/bill-tos/{bill_to_id}/refresh", headers=admin)
    assert resp.status_code == 200
    assert resp.json()["locations_sync"] == {"total": 3, "added": 1, "updated": 2, "removed": 1}
    assert resp.json()["location_count"] == 3

    rows = client.get(f"/v1/bill-tos/{bill_to_id}/locations", headers=admin).json()
    by_id = {r["pestpac_location_id"]: r for r in rows}
    assert by_id[900001]["pestpac_company"] == "ACME TACOS - STORE #436 (RENAMED)"
    assert by_id[900003]["removed_at"] is not None  # kept, not deleted
    assert rows[-1]["pestpac_location_id"] == 900003  # removed ones listed last


def test_location_moving_between_bill_tos_is_reassigned(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    first = _onboard(client, admin, world.company_a, 180020).json()
    # The cached client reuses its token, so no token call is guaranteed.
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        # PestPac now lists store #436 under bill-to 175101 instead.
        _mock(rsps, 175101, items=[LOCATIONS_FIXTURE[0]])
        moved = client.post(f"/v1/bill-tos/{world.bill_to_a}/refresh", headers=admin)
    assert moved.json()["locations_sync"]["updated"] == 1
    with SessionLocal() as db:
        location = db.scalar(select(Location).where(Location.pestpac_location_id == 900001))
        assert str(location.bill_to_id) == str(world.bill_to_a)
    first_now = client.get(f"/v1/bill-tos/{first['id']}", headers=admin).json()
    assert first_now["location_count"] == 2


def test_location_under_another_bill_to_fails_onboarding_cleanly(client, world):
    admin = headers_for(client, world.emails["admin_a"])
    bad = pestpac_locations(180020) + [dict(LOCATIONS_FIXTURE[0], LocationID=900009, BillToID=1)]
    with responses.RequestsMock() as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
        rsps.get(f"{PESTPAC_BASE}/BillTos/180020", body=json.dumps(pestpac_bill_to_body(180020)))
        rsps.add_callback(responses.GET, LOCATIONS_URL, locations_callback({180020: bad}))
        resp = _onboard(client, admin, world.company_a)
    assert resp.status_code == 502
    _assert_not_onboarded(180020)


def test_failure_on_a_later_page_writes_nothing(client, world, page_size):
    page_size(2)
    admin = headers_for(client, world.emails["admin_a"])
    with responses.RequestsMock() as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
        rsps.get(f"{PESTPAC_BASE}/BillTos/180020", body=json.dumps(pestpac_bill_to_body(180020)))
        rsps.get(
            f"{PESTPAC_BASE}/BillTos/180020/locations/pageable?skip=0&take=2",
            body=json.dumps(pestpac_locations(180020)[:2]),
            match_querystring=True,
        )
        rsps.get(
            f"{PESTPAC_BASE}/BillTos/180020/locations/pageable?skip=2&take=2",
            status=503,
            match_querystring=True,
        )
        resp = _onboard(client, admin, world.company_a)
    assert resp.status_code == 502
    _assert_not_onboarded(180020)


def test_failed_refresh_keeps_existing_locations(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    bill_to_id = _onboard(client, admin, world.company_a).json()["id"]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
        rsps.get(f"{PESTPAC_BASE}/BillTos/180020", body=json.dumps(pestpac_bill_to_body(180020)))
        rsps.add_callback(responses.GET, LOCATIONS_URL, lambda request: (500, {}, "boom"))
        resp = client.post(f"/v1/bill-tos/{bill_to_id}/refresh", headers=admin)
    assert resp.status_code == 502
    rows = client.get(f"/v1/bill-tos/{bill_to_id}/locations", headers=admin).json()
    assert len(rows) == 3 and all(r["removed_at"] is None for r in rows)


def test_paging_that_does_not_advance_is_detected(client, world, page_size):
    page_size(2)
    admin = headers_for(client, world.emails["admin_a"])
    full_page = json.dumps(pestpac_locations(180020)[:2])
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "t"})
        rsps.get(f"{PESTPAC_BASE}/BillTos/180020", body=json.dumps(pestpac_bill_to_body(180020)))
        rsps.add_callback(responses.GET, LOCATIONS_URL, lambda request: (200, {}, full_page))
        resp = _onboard(client, admin, world.company_a)
    assert resp.status_code == 502
    assert "not advancing" in resp.json()["detail"]


def test_page_cap(client, world, page_size):
    page_size(1, max_pages=2)
    admin = headers_for(client, world.emails["admin_a"])
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _mock(rsps, 180020)
        resp = _onboard(client, admin, world.company_a)
    assert resp.status_code == 502
    assert "PESTPAC_MAX_PAGES" in resp.json()["detail"]


def _assert_not_onboarded(pestpac_bill_to_id: int) -> None:
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillTo)
                .where(BillTo.pestpac_bill_to_id == pestpac_bill_to_id)
            )
            == 0
        )
        fixture_ids = [loc["LocationID"] for loc in LOCATIONS_FIXTURE]
        assert (
            db.scalar(
                select(func.count())
                .select_from(Location)
                .where(Location.pestpac_location_id.in_(fixture_ids))
            )
            == 0
        )


def test_a_companys_locations_span_its_bill_tos(client, world, pestpac):
    admin = headers_for(client, world.emails["admin_a"])
    assert _onboard(client, admin, world.company_a).status_code == 201  # 3 more stores

    rows = client.get(f"/v1/companies/{world.company_a}/locations", headers=admin).json()
    bill_tos = {r["bill_to_id"] for r in rows}
    assert len(bill_tos) == 2 and str(world.bill_to_a) in bill_tos  # the world's and the new one
    assert str(world.location_a) in {r["id"] for r in rows}
    assert len(rows) == 4
    assert all("open_order_count" in r for r in rows)
    # Company B has no bill-tos: nothing of company A's shows there.
    platform = headers_for(client, world.emails["platform_admin"])
    assert client.get(f"/v1/companies/{world.company_b}/locations", headers=platform).json() == []
