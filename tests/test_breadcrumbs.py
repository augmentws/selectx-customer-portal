"""Detail pages carry their parents (`trail`) so the UI can show where a record sits."""

from tests.conftest import headers_for


def _trail(client, world, path: str) -> list[tuple[str, str, str]]:
    resp = client.get(path, headers=headers_for(client, world.emails["staff_a"]))
    assert resp.status_code == 200, resp.text
    return [(c["kind"], c["id"], c["name"]) for c in resp.json()["trail"]]


def test_company_trail_is_its_operator(client, world):
    assert _trail(client, world, f"/v1/companies/{world.company_a}") == [
        ("operator", str(world.op_a), "Operator A"),
    ]


def test_bill_to_trail(client, world):
    assert _trail(client, world, f"/v1/bill-tos/{world.bill_to_a}") == [
        ("operator", str(world.op_a), "Operator A"),
        ("company", str(world.company_a), "Acme Restaurants"),
    ]


def test_location_trail(client, world):
    assert _trail(client, world, f"/v1/locations/{world.location_a}") == [
        ("operator", str(world.op_a), "Operator A"),
        ("company", str(world.company_a), "Acme Restaurants"),
        ("bill_to", str(world.bill_to_a), "Acme HQ"),
    ]


def test_service_report_trail_ends_at_its_location(client, world):
    assert _trail(client, world, f"/v1/service-reports/{world.report_a}") == [
        ("operator", str(world.op_a), "Operator A"),
        ("company", str(world.company_a), "Acme Restaurants"),
        ("bill_to", str(world.bill_to_a), "Acme HQ"),
        ("location", str(world.location_a), "ACME TACOS - STORE #1"),
    ]
