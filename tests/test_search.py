"""Header search: each kind is scoped to the operators where the caller can open it."""

import pytest

from tests.conftest import headers_for


def _search(client, world, actor: str, q: str) -> list[tuple[str, str]]:
    resp = client.get(
        "/v1/search", params={"q": q}, headers=headers_for(client, world.emails[actor])
    )
    assert resp.status_code == 200, resp.text
    return [(h["kind"], h["title"]) for h in resp.json()["items"]]


def test_names_match_anywhere_case_insensitively(client, world):
    assert _search(client, world, "staff_a", "acme") == [
        ("company", "Acme Restaurants"),
        ("bill_to", "Acme HQ"),
        ("location", "ACME TACOS - STORE #1"),
    ]


def test_store_number_finds_the_location(client, world):
    assert ("location", "ACME TACOS - STORE #1") in _search(client, world, "staff_a", "store #1")


@pytest.mark.parametrize(
    ("actor", "found"),
    [("admin_a", False), ("staff_a", False), ("admin_b", True), ("platform_admin", True)],
)
def test_other_operators_records_are_never_returned(client, world, actor, found):
    assert (("company", "Beta Hotels") in _search(client, world, actor, "beta")) is found


def test_operators_are_found_by_those_who_can_see_them(client, world):
    assert _search(client, world, "admin_b", "operator") == [("operator", "Operator B")]
    assert _search(client, world, "platform_admin", "operator") == [
        ("operator", "Operator A"),
        ("operator", "Operator B"),
    ]


def test_ids_match_exactly(client, world):
    assert _search(client, world, "staff_a", "175101") == [("bill_to", "Acme HQ")]
    assert _search(client, world, "staff_a", "800001") == [("location", "ACME TACOS - STORE #1")]
    assert _search(client, world, "staff_a", "80000") == []


def test_orders_open_on_their_location(client, world):
    resp = client.get(
        "/v1/search", params={"q": "700001"}, headers=headers_for(client, world.emails["staff_a"])
    )
    [hit] = resp.json()["items"]
    assert hit["kind"] == "service_order"
    assert hit["id"] == str(world.service_order_a)
    assert hit["location_id"] == str(world.location_a)
    assert hit["detail"] == "ACME TACOS - STORE #1"


def test_invoices_need_billing_read(client, world):
    assert _search(client, world, "admin_a", "A1") == [("invoice", "Invoice A1")]
    assert _search(client, world, "staff_a", "A1") == []


def test_like_wildcards_are_literal(client, world):
    assert _search(client, world, "platform_admin", "%%") == []
    assert _search(client, world, "platform_admin", "__") == []


def test_query_needs_two_characters(client, world):
    resp = client.get(
        "/v1/search", params={"q": "a"}, headers=headers_for(client, world.emails["staff_a"])
    )
    assert resp.status_code == 422
