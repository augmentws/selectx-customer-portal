"""The Restaurant Leader Report import and the contact lists. Who may call them is in
tests/test_access_matrix.py."""

from datetime import UTC, datetime

import pytest

from app.db.session import SessionLocal
from app.import_leader_report import main
from app.models import Contact, ContactLink, Location
from app.services.contacts import LeaderReportError, import_leader_report
from tests.conftest import headers_for

HEADER = [
    "Restaurant Number",
    "Restaurant Name Number",
    "Concept",
    "Restaurant Status",
    "Open Date",
    "Phone Number",
    "Address",
    "City",
    "County",
    "State",
    "Postal Code",
    "Country",
    "State Code",
    "State Code County",
    "State Code City",
    "Email Address",
    "Sub Region",
    "Region",
    "Regional Director",
    "Regional Director Email",
    "Regional Director Phone",
    "Executive Team Director",
    "Executive Team Director Email",
    "Executive Team Director Phone",
    "Team Director",
    "Team Director Email",
    "Team Director Phone",
    "Area Manager / Team Leader / Apprentice Team Leader",
    "Area Manager / Team Leader / Apprentice Team Leader Email",
    "Area Manager / Team Leader / Apprentice Team Leader Phone",
]


def store(number: str, name: str, status: str = "OPEN", td=("Tia Director", "TDir@acme.test")):
    row = [""] * len(HEADER)
    row[0], row[1], row[2], row[3] = number, f"{name} - {number}", "CMG", status
    row[5], row[15], row[18] = "+1-212-555-0100", f"ny.{number}@acme.test", " "
    row[21:24] = ["Eve Exec", "eve@acme.test", "+1 (206) 555-0101"]
    row[24:27] = [td[0], td[1], "+1 (973) 555-0102"]
    # The last column is sometimes missing from the export.
    row[27:29] = ["Rae Leader", "rae@acme.test"]
    return row[:29]


def report(*stores: list[str]) -> list[list[str]]:
    # As exported: a title line, and the header sorted in among the stores.
    return [["Restaurant Leaders"], stores[0], HEADER, *stores[1:]]


@pytest.fixture
def second_location(world):
    """Store #2 under the same bill-to; PROJECT in the report, so it gets nothing."""
    with SessionLocal() as db:
        location = Location(
            operator_id=world.op_a,
            bill_to_id=world.bill_to_a,
            pestpac_location_id=800002,
            pestpac_company="ACME TACOS - STORE #2",
            pestpac_active=True,
            pestpac_fetched_at=datetime.now(UTC),
        )
        db.add(location)
        db.commit()
        return location.id


def _import(world, rows):
    with SessionLocal() as db:
        result = import_leader_report(db, world.op_a, world.company_a, rows)
        db.commit()
        return result


def test_imports_open_stores_matching_a_location(client, world, second_location):
    result = _import(
        world,
        report(
            store("1", "Grand Central"), store("2", "Vernon", "PROJECT"), store("9", "Elsewhere")
        ),
    )
    assert (result.rows, result.matched, result.unmatched) == (3, 1, ["9"])
    assert dict(result.skipped_status) == {"PROJECT": 1}
    assert (result.descriptions_changed, dict(result.contacts), dict(result.links)) == (
        1,
        {"created": 4},
        {"created": 4},
    )

    staff = headers_for(client, world.emails["staff_a"])
    location = client.get(f"/v1/locations/{world.location_a}", headers=staff).json()
    assert location["description"] == "Grand Central - 1"
    contacts = client.get(f"/v1/locations/{world.location_a}/contacts", headers=staff).json()
    # The store first, then its leaders from the top down; emails lower-cased.
    assert [(c["role"], c["name"], c["email"], c["phone"]) for c in contacts] == [
        ("store", "Grand Central - 1", "ny.1@acme.test", "+1-212-555-0100"),
        ("executive_team_director", "Eve Exec", "eve@acme.test", "+1 (206) 555-0101"),
        ("team_director", "Tia Director", "tdir@acme.test", "+1 (973) 555-0102"),
        ("restaurant_leader", "Rae Leader", "rae@acme.test", None),
    ]
    assert {c["source"] for c in contacts} == {"restaurant_leader_report"}

    # The PROJECT store gets neither contacts nor a description.
    project = client.get(f"/v1/locations/{second_location}", headers=staff).json()
    assert project["description"] is None
    assert client.get(f"/v1/locations/{second_location}/contacts", headers=staff).json() == []
    # Nothing is linked to the bill-to itself.
    assert client.get(f"/v1/bill-tos/{world.bill_to_a}/contacts", headers=staff).json() == []


def test_leaders_are_shared_across_stores(world, second_location):
    _import(world, report(store("1", "Grand Central"), store("2", "Vernon")))
    with SessionLocal() as db:
        assert db.query(Contact).count() == 5  # Two stores, three shared leaders.
        assert db.query(ContactLink).count() == 8


def test_reimport_replaces_a_changed_leader(client, world):
    _import(world, report(store("1", "Grand Central")))
    again = _import(world, report(store("1", "Grand Central")))
    assert (again.descriptions_changed, dict(again.contacts), dict(again.links)) == (0, {}, {})

    changed = _import(world, report(store("1", "Grand Central", td=("Ned New", "ned@acme.test"))))
    assert dict(changed.contacts) == {"created": 1, "removed": 1}
    assert dict(changed.links) == {"created": 1, "removed": 1}
    staff = headers_for(client, world.emails["staff_a"])
    contacts = client.get(f"/v1/locations/{world.location_a}/contacts", headers=staff).json()
    assert [c["name"] for c in contacts if c["role"] == "team_director"] == ["Ned New"]

    # The old director comes back if a later report lists them again.
    back = _import(world, report(store("1", "Grand Central")))
    assert dict(back.links) == {"restored": 1, "removed": 1}
    assert dict(back.contacts) == {"updated": 1, "removed": 1}


def test_wrong_layout_is_refused(world):
    # A column dropped after the store number: everything after it moves left.
    shifted = [*HEADER[:2], *HEADER[3:]]
    with pytest.raises(LeaderReportError, match="unexpected columns"):
        _import(world, [store("1", "Grand Central"), shifted])
    with pytest.raises(LeaderReportError, match="expected one header row, found 0"):
        _import(world, [store("1", "Grand Central")])


def test_command_dry_run_saves_nothing(world, tmp_path):
    path = tmp_path / "report.csv"
    path.write_text("\n".join(",".join(row) for row in report(store("1", "Grand Central"))))
    args = ["--operator-id", str(world.op_a), "--company-id", str(world.company_a), str(path)]
    assert main([*args, "--dry-run"]) == 0
    with SessionLocal() as db:
        assert db.query(ContactLink).count() == 0
    assert main(args) == 0
    with SessionLocal() as db:
        assert db.query(ContactLink).count() == 4
    # The company must belong to the operator.
    assert main(["--operator-id", str(world.op_b), *args[2:]]) == 1
