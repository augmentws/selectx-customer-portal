"""Risk inspection lists (company and location) and the report: the PDF sample's submission,
linked to the world's location, with photos stored. Who may call them is in
tests/test_access_matrix.py."""

import pytest

from app.db.session import SessionLocal
from app.models import InspectionKind, Tenant
from app.services.gocanvas_connection import get_gocanvas_client
from app.services.inspection_photos import fetch_submission_photos
from app.services.inspections import import_form, store_submission
from tests.conftest import headers_for
from tests.test_inspection_photos import PEST_VALUE, SUBMISSION_ID, gocanvas  # noqa: F401
from tests.test_inspections import FORM, submission


@pytest.fixture
def linked(world, gocanvas, storage):  # noqa: F811
    """The PDF sample under store #1 (the world's location), with its photos fetched, and an
    older inspection of the same store."""
    payload = submission("pdf_sample")
    older = submission("ramp_digit")
    for p in (payload, older):
        for response in p["responses"]:
            if response["export_label"] == "StoreNumbe":
                response["value"] = "Chipotle - Store #1"
    gocanvas.values[PEST_VALUE] = 2
    with SessionLocal() as db:
        import_form(db, world.op_a, FORM, InspectionKind.risk)
        sub = store_submission(db, world.op_a, payload).submission
        store_submission(db, world.op_a, older)
        db.commit()
        client = get_gocanvas_client(db, db.get(Tenant, world.op_a))
        fetch_submission_photos(db, client, storage, sub)
        return sub.id


def test_company_bill_to_and_location_lists(client, world, linked):
    staff = headers_for(client, world.emails["staff_a"])
    by_company = client.get(f"/v1/companies/{world.company_a}/risk-inspections", headers=staff)
    by_location = client.get(f"/v1/locations/{world.location_a}/risk-inspections", headers=staff)
    by_bill_to = client.get(f"/v1/bill-tos/{world.bill_to_a}/risk-inspections", headers=staff)
    assert by_company.status_code == by_location.status_code == by_bill_to.status_code == 200
    # The company has one bill-to with one location, so all three lists agree.
    assert by_company.json() == by_location.json() == by_bill_to.json()
    newest, older, undated = by_company.json()
    assert newest["inspected_at"] > older["inspected_at"]
    # The world's own inspection has no date (or zones): listed last.
    assert (undated["gocanvas_submission_id"], undated["zones_inspected"]) == (1, 0)
    assert {
        k: newest[k]
        for k in (
            "id",
            "gocanvas_submission_id",
            "location_name",
            "ramp_recommendation",
            "highest_risk",
            "zones_inspected",
            "zones_with_activity",
        )
    } == {
        "id": str(linked),
        "gocanvas_submission_id": SUBMISSION_ID,
        "location_name": "ACME TACOS - STORE #1",
        "ramp_recommendation": 3,
        "highest_risk": 4,  # Service Line / Food Preparation
        "zones_inspected": 7,
        "zones_with_activity": 1,  # Front of House (flies)
    }
    # Another company's list doesn't include them.
    admin_b = headers_for(client, world.emails["admin_b"])
    other = client.get(f"/v1/companies/{world.company_b}/risk-inspections", headers=admin_b)
    assert other.json() == []


def test_report_has_what_the_pdf_shows(client, world, linked):
    staff = headers_for(client, world.emails["staff_a"])
    report = client.get(f"/v1/risk-inspections/{linked}", headers=staff).json()
    assert [c["kind"] for c in report["trail"]] == ["operator", "company", "bill_to", "location"]
    assert (report["inspector_name"], report["inspected_at"]) == (
        "Test Inspector",
        "2026-10-28T05:07:00",
    )
    front = report["zones"][0]
    assert (front["name"], front["pest_types"], front["has_activity"]) == (
        "Front of House",
        ["Flies"],
        True,
    )
    assert (front["sanitation_risk"], front["structural_risk"], front["overall_risk"]) == (3, 2, 3)
    pest_photos = [p for p in front["photos"] if p["category"] == "pest"]
    assert [p["position"] for p in pest_photos] == [1, 2]
    # Every photo opens through the stored files endpoint.
    photo = client.get(f"/v1/files/{pest_photos[0]['file_id']}", headers=staff)
    assert (photo.status_code, photo.headers["content-type"]) == (200, "image/jpeg")

    assert [z["inspected"] for z in report["zones"]][6:8] == ["n/a", "n/a"]
    assert report["zones"][8]["attributes"]["paneling"] == ["Corrugated Tin and Trim"]
    # Materials in the form's order, as the PDF lists them.
    assert [m["material_key"] for m in report["materials"]][:3] == [
        "door_sweeps",
        "chicken_fence",
        "copper_mesh",
    ]
    assert report["manager_summary"] == "Sample note for ServiceManSummary."
    assert (report["photos_pending"], report["parse_warning_count"]) == (0, 0)


def test_unknown_inspection_is_404(client, world):
    staff = headers_for(client, world.emails["staff_a"])
    resp = client.get("/v1/risk-inspections/00000000-0000-0000-0000-000000000000", headers=staff)
    assert resp.status_code == 404
