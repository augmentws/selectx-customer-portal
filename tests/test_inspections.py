"""GoCanvas risk inspections: form import, parsing, revisions, and linking.

Fixtures are real submissions of the Chipotle RiskGate form with names, addresses, store
numbers, and notes replaced. `submission_pdf_sample` is the one behind
docs/risk-submissions/Chipotle_Riskgate_Inspection_Form.pdf, so its expectations are the PDF's.
"""

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app import load_inspections
from app.db.session import SessionLocal
from app.models import InspectionKind, InspectionSubmission, ServiceOrder
from app.services.inspections import (
    InspectionError,
    import_form,
    split_options,
    store_submission,
)

FIXTURES = Path(__file__).parent / "fixtures" / "gocanvas"
FORM = json.loads((FIXTURES / "risk_form.json").read_text())
SERVICE_LINE_AREAS = [
    "Point of Sale (Smart Safe)",
    "Front Make Line (FML Wall Cavity & FML Internals)",
    "Digital Make Line / Second Make Line (Wall Junction, IT Cabinet, & Internals)",
    "Grill",
    "Fryer",
]


def submission(name: str) -> dict:
    return json.loads((FIXTURES / f"submission_{name}.json").read_text())


def load(db, operator_id, *names: str) -> list[InspectionSubmission]:
    import_form(db, operator_id, FORM, InspectionKind.risk)
    stored = [store_submission(db, operator_id, submission(n)).submission for n in names]
    db.commit()
    return stored


def zones_by_key(stored: InspectionSubmission) -> dict:
    return {zone.zone_key: zone for zone in stored.risk_zones}


def issues(stored: InspectionSubmission) -> list[tuple[str | None, str]]:
    return [(w["field_key"], w["issue"]) for w in stored.parse_warnings]


def test_form_import_derives_zones_and_maps_every_entry(world):
    with SessionLocal() as db:
        form = import_form(db, world.op_a, FORM, InspectionKind.risk)
        db.commit()
        assert [zone.name for zone in form.zones] == [
            "Front of House",
            "Restrooms",
            "Service Line / Food Preparation",
            "Kitchen Support Areas",
            "Office & Administrative Areas",
            "Rear Entry & Trash Room",
            "Basement (if applicable)",
            "Shared Structures /Adjacent Tenancies",
            "Ceiling Voids, Exterior Perimeter, Paneling, Dumbwaiter/Elevator, Mall location",
        ]
        assert len(form.fields) == 190
        assert [f.label for f in form.fields if f.field_key is None] == []
        by_entry = {f.entry_id: f for f in form.fields}
        # Front of House: areas are multi-select, pest type single; options trimmed.
        assert (by_entry[753278043].field_key, by_entry[753278043].multi_select) == ("areas", True)
        assert (by_entry[753278051].field_key, by_entry[753278051].multi_select) == (
            "pest_types",
            False,
        )
        assert by_entry[753278044].options == ["Metal", "Wood"]
        # RAMP and the summary sit in the last zone's section but belong to the submission.
        assert (by_entry[753278214].field_key, by_entry[753278214].zone_key) == (
            "ramp_recommendation",
            None,
        )
        assert by_entry[753278217].field_key == "material.chicken_fence"

        # Re-importing replaces the map rather than adding to it.
        form = import_form(db, world.op_a, FORM, InspectionKind.risk)
        db.commit()
        assert (len(form.zones), len(form.fields)) == (9, 190)


def test_pdf_sample_matches_the_pdf_report(world):
    with SessionLocal() as db:
        [stored] = load(db, world.op_a, "pdf_sample")
        assert stored.inspector_name == "Test Inspector"
        assert stored.inspected_at.isoformat() == "2026-10-28T05:07:00"
        assert (stored.store_label, stored.store_number) == ("Chipotle - Store #9001", "9001")
        assert stored.risk_summary.ramp_recommendation == 3
        assert stored.parse_warnings == [] and stored.unmapped_entry_ids == []

        # The PDF's station details, zone by zone.
        rows = [
            (
                z.inspected,
                z.areas,
                z.all_areas_inspected,
                z.doors_are,
                z.door_sweeps_ok,
                z.doors_aligned,
                z.rodent_activity,
                z.pest_activity,
                z.pest_types,
                (z.sanitation_risk, z.structural_risk, z.overall_risk),
            )
            for z in stored.risk_zones
        ]
        assert rows == [
            (
                "yes",
                ["Beverage Station", "Booths/Seating", "Guest Ordering Line"],
                None,
                ["Metal"],
                False,
                True,
                False,
                True,
                ["Flies"],
                (3, 2, 3),
            ),
            ("yes", ["Mens", "Womans"], None, ["Metal"], False, True, False, False, [], (1, 2, 2)),
            ("yes", SERVICE_LINE_AREAS, True, [], None, None, False, False, [], (3, 4, 4)),
            ("yes", rows[3][1], True, ["Metal"], True, True, False, False, [], (3, 3, 3)),
            ("yes", ["Managers Office"], True, ["Metal"], False, True, False, False, [], (1, 3, 2)),
            ("yes", [], None, ["Metal"], True, True, False, False, [], (2, 1, 1)),
            ("n/a", [], None, [], None, None, None, None, [], (None, None, None)),
            ("n/a", [], None, [], None, None, None, None, [], (None, None, None)),
            ("yes", [], None, [], None, None, False, False, [], (1, 1, 1)),
        ]
        assert len(rows[3][1]) == 12 and rows[3][1][0] == "Chefs table (Behind FML)"
        zones = zones_by_key(stored)
        assert zones["rear_entry_trash_room"].attributes == {
            "dumpster": ["Shared"],
            "trash_room": ["Separated / Off Premise"],
        }
        assert zones[stored.risk_zones[8].zone_key].attributes == {
            "ceiling": ["Drop Ceiling"],
            "exterior_perimeter": ["Patio", "Parking Lot"],
            "paneling": ["Corrugated Tin and Trim"],
            "in_mall": False,
            "dumbwaiter_operational": False,
        }
        # The zone summary: only Front of House had activity.
        assert [z.has_activity for z in stored.risk_zones] == [True] + [False] * 8
        assert {m.material_key: m.used for m in stored.risk_materials} == {
            "door_sweeps": False,
            "chicken_fence": False,
            "copper_mesh": False,
            "excluder_pad": False,
            "tin_cats": False,
            "snap_traps": False,
            "metal_flashing": False,
            "caulking_sealant": False,
        }


def test_every_response_is_kept_as_received(world):
    with SessionLocal() as db:
        [stored] = load(db, world.op_a, "pdf_sample")
        source = submission("pdf_sample")["responses"]
        assert [
            (r.gocanvas_response_id, r.entry_id, r.label, r.displayed) for r in stored.responses
        ] == [(r["id"], r["entry_id"], r["label"], r["displayed"]) for r in source]
        assert [r.value if r.value is not None else r.value_json for r in stored.responses] == [
            r["value"] for r in source
        ]
        assert stored.raw_payload == submission("pdf_sample")


@pytest.mark.parametrize("name", ["newline_separated", "comma_separated"])
def test_multi_selects_split_on_any_separator(world, name):
    with SessionLocal() as db:
        [stored] = load(db, world.op_a, name)
        zones = zones_by_key(stored)
        assert set(zones["front_of_house"].areas) == {
            "Beverage Station",
            "Booths/Seating",
            "Guest Ordering Line",
        }
        assert set(zones["restrooms"].areas) == {"Mens", "Womans"}
        assert not [w for w in stored.parse_warnings if "options" in w["issue"]]


def test_split_options_keeps_options_that_contain_commas():
    options = ["Grill", SERVICE_LINE_AREAS[2], "Fryer"]
    assert split_options(f"Grill,{SERVICE_LINE_AREAS[2]},Fryer ", options) == (
        ["Grill", SERVICE_LINE_AREAS[2], "Fryer"],
        [],
    )
    assert split_options("grill\r\nWok", options) == (["Grill", "Wok"], ["Wok"])
    assert split_options("", options) == ([], [])


def test_retired_options_are_kept_with_a_warning(world):
    with SessionLocal() as db:
        [stored] = load(db, world.op_a, "retired_option")
        assert zones_by_key(stored)["front_of_house"].pest_types == ["Rats"]
        assert ("pest_types", "'Rats' is not one of the form's options") in issues(stored)


def test_pest_types_get_one_spelling_across_zones(world):
    payload = submission("pdf_sample")
    for response in payload["responses"]:
        if response["export_label"] == "TypeOfPest":
            response["value"] = "Occasional Invader"
    with SessionLocal() as db:
        import_form(db, world.op_a, FORM, InspectionKind.risk)
        stored = store_submission(db, world.op_a, payload).submission
        assert zones_by_key(stored)["front_of_house"].pest_types == ["Occasional Invaders"]
        assert stored.parse_warnings == []


def test_ramp_digits_and_blanks(world):
    with SessionLocal() as db:
        digit, blank = load(db, world.op_a, "ramp_digit", "newline_separated")
        assert digit.risk_summary.ramp_recommendation == 3
        assert blank.risk_summary.ramp_recommendation is None
        assert "ramp_recommendation" not in [key for key, _ in issues(blank)]


def test_material_quantities_from_older_submissions(world):
    with SessionLocal() as db:
        [stored] = load(db, world.op_a, "material_quantities")
        materials = {m.material_key: (m.used, m.quantity) for m in stored.risk_materials}
        assert materials["copper_mesh"] == (True, Decimal("24"))
        assert materials["snap_traps"] == (True, Decimal("50"))
        assert not [w for w in stored.parse_warnings if w["field_key"].startswith("material.")]


def test_text_in_a_score_is_left_null_and_warned(world):
    with SessionLocal() as db:
        [stored] = load(db, world.op_a, "text_in_score")
        zone = zones_by_key(stored)["service_line_food_preparation"]
        assert zone.structural_risk is None
        assert ("structural_risk", "expected a risk score from 1 to 5") in issues(stored)
        [raw] = [r for r in stored.responses if r.export_label == "Structural2"]
        assert raw.value.startswith("Nothing observed")


def test_unpadded_time_and_blank_store(world):
    with SessionLocal() as db:
        short, blank = load(db, world.op_a, "short_time", "blank_store")
        assert short.inspected_at.strftime("%H:%M") == "20:45"
        assert (blank.store_label, blank.store_number, blank.location_id) == (None, None, None)


def test_revisions_replace_the_parsed_rows_and_stale_ones_are_ignored(world):
    original = submission("pdf_sample")
    revised = copy.deepcopy(original)
    revised.update(revision=True, revised_at="2026-10-30T12:00:00Z")
    for response in revised["responses"]:
        if response["export_label"] == "Sanitation":
            response["value"] = "5"
    with SessionLocal() as db:
        import_form(db, world.op_a, FORM, InspectionKind.risk)
        assert store_submission(db, world.op_a, original).outcome == "created"
        db.commit()
        assert store_submission(db, world.op_a, original).outcome == "unchanged"
        result = store_submission(db, world.op_a, revised)
        db.commit()
        assert result.outcome == "updated"
        stored = result.submission
        assert (len(stored.responses), len(stored.risk_zones)) == (190, 9)
        assert zones_by_key(stored)["front_of_house"].sanitation_risk == 5
        # The original arriving late doesn't undo the revision.
        assert store_submission(db, world.op_a, original).outcome == "stale"
        db.commit()
        db.refresh(stored)
        assert zones_by_key(stored)["front_of_house"].sanitation_risk == 5
        assert db.scalars(select(InspectionSubmission)).all() == [stored]


def test_links_the_order_by_work_order_number_else_the_store(world):
    payload = submission("pdf_sample")
    for response in payload["responses"]:
        if response["export_label"] == "WorkOrderI":
            response["value"] = "5550001"
        if response["export_label"] == "StoreNumbe":
            response["value"] = "Chipotle - Store #1"
    with SessionLocal() as db:
        import_form(db, world.op_a, FORM, InspectionKind.risk)
        # The store number alone finds the location ("ACME TACOS - STORE #1").
        stored = store_submission(db, world.op_a, payload).submission
        assert (stored.location_id, stored.service_order_id) == (world.location_a, None)

        db.get(ServiceOrder, world.service_order_a).order_number = "5550001"
        payload["revised_at"] = "2026-10-30T12:00:00Z"
        stored = store_submission(db, world.op_a, payload).submission
        assert (stored.location_id, stored.service_order_id) == (
            world.location_a,
            world.service_order_a,
        )
        # Another operator's copy of the submission never links operator A's order or store.
        import_form(db, world.op_b, FORM, InspectionKind.risk)
        other = store_submission(db, world.op_b, payload).submission
        assert (other.location_id, other.service_order_id) == (None, None)


def test_submission_needs_its_form_and_operator_scope(world):
    with SessionLocal() as db:
        with pytest.raises(InspectionError, match="hasn't been imported"):
            store_submission(db, world.op_a, submission("pdf_sample"))
        import_form(db, world.op_a, FORM, InspectionKind.risk)
        with pytest.raises(InspectionError, match="hasn't been imported"):
            store_submission(db, world.op_b, submission("pdf_sample"))
        with pytest.raises(InspectionError, match="Not a GoCanvas submission"):
            store_submission(db, world.op_a, FORM)


def test_loader_command(world, tmp_path, caplog):
    form_file = tmp_path / "form.json"
    form_file.write_text(json.dumps(FORM))
    files = [str(FIXTURES / f"submission_{n}.json") for n in ("pdf_sample", "ramp_digit")]
    args = ["--operator-id", str(world.op_a), "--form", str(form_file), "--kind", "risk"]
    args.append("--no-photos")  # photo fetching is covered in test_inspection_photos.py
    caplog.set_level("INFO")
    assert load_inspections.main([*args, *files]) == 0
    assert "Submissions: 2 created" in caplog.text
    assert load_inspections.main([*args, *files]) == 0
    assert "Submissions: 2 unchanged" in caplog.text
    assert load_inspections.main([*args, "--reparse", *files]) == 0
    assert "Submissions: 2 updated" in caplog.text
