import io
from datetime import UTC, datetime

import pytest
from PIL import Image

from app.db.session import SessionLocal
from app.integrations.openrouter import Usage
from app.models import Document, InspectionFinding, Note, ServiceOrder, StoredFile
from app.services import llm_tasks
from tests.conftest import headers_for
from tests.test_service_orders import _run_worker

FIELDS = [
    {"key": "summary", "label": "Inspection summary", "type": "paragraphs", "llm": True},
    {
        "key": "sections",
        "label": "Findings",
        "type": "sections",
        "llm": True,
        "help": "One per area",
    },
    {"key": "recommendations", "label": "Recommendations", "type": "list", "llm": True},
    {"key": "distribution", "label": "Distribution", "type": "text", "default": "Leadership"},
]
HTML = """<h1>{{ service_order.order_number if service_order else '' }}</h1>
{% for p in fields.summary %}<p>{{ p|rich }}</p>{% endfor %}
{% for s in fields.sections %}<h2>{{ s.heading }}</h2>{% for p in s.paragraphs %}<p>{{ p|rich }}</p>{% endfor %}{% endfor %}
<ul>{% for r in fields.recommendations %}<li>{{ r|rich }}</li>{% endfor %}</ul>
<p>{{ fields.distribution }}</p>
{% for photo in photos %}<figure><img src="{{ photo.src }}"><figcaption>{{ photo.caption }}</figcaption></figure>{% endfor %}"""  # noqa: E501
PROMPT = "Write a pest-control service report from the technician's notes."

DRAFT = {
    "summary": ["A **quality control** inspection was completed."],
    "sections": [{"heading": "Trash Room", "paragraphs": ["An opening was found."]}],
    "recommendations": ["Seal the **trash room** opening."],
    "findings": {
        "visit_type": "qc_inspection",
        "rodent_activity": "none",
        "rodent_species": [],
        "rodent_evidence": [],
        "rodents_captured": None,
        "activity_locations": [],
        "devices_serviced": 6,
        "exclusion_status": "compromised",
        "sanitation_rating": "satisfactory",
        "structural_findings": [
            {
                "location": "trash room",
                "issue": "opening at the wall base",
                "category": "wall/floor gap",
                "status": "open",
            }
        ],
        "sanitation_findings": [],
        "other_pests": [
            {"pest": "gnats", "severity": "low", "location": "mop sink"},
        ],
        "summary": "No rodent activity; an opening was found in the trash room.",
    },
}


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (3000, 2000), (120, 130, 140)).save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture
def admin(client, world):
    return headers_for(client, world.emails["admin_a"])


@pytest.fixture
def template(client, world):
    platform = headers_for(client, world.emails["platform_admin"])
    resp = client.post(
        f"/v1/companies/{world.company_a}/report-templates",
        json={"name": "Service report", "html": HTML, "fields": FIELDS, "prompt": PROMPT},
        headers=platform,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def visit(world, storage):
    """Notes and photos around the world's order (worked 2026-10-05 09:30): on the day, the day
    before, linked to the order, and outside the window."""
    with SessionLocal() as db:
        now = datetime.now(UTC)

        def note(n, date, text, *, linked=False):
            return Note(
                operator_id=world.op_a,
                pestpac_note_id=n,
                note_date=date,
                note_code="SERVICE",
                note=text,
                created_by_user="PTECH",
                location_id=world.location_a,
                service_order_id=world.service_order_a if linked else None,
                pestpac_fetched_at=now,
            )

        def photo(n, date, name, *, stored=True):
            key = f"test/visit/{n}" if stored else None
            if stored:
                storage.put(key, _jpeg(), "image/jpeg")
            return Document(
                operator_id=world.op_a,
                document_type="LocationDocument",
                pestpac_document_id=n,
                name=name,
                file_name=f"{name}.jpg",
                document_date=date,
                location_id=world.location_a,
                pestpac_location_id=800001,
                file=StoredFile(
                    operator_id=world.op_a,
                    company_id=world.company_a,
                    source="pestpac_document",
                    storage_key=key,
                    content_type="image/jpeg",
                    size_bytes=len(_jpeg()),
                    sha256="0" * 64,
                )
                if stored
                else None,
                pestpac_fetched_at=now,
            )

        db.add_all(
            [
                note(1, datetime(2026, 10, 5, 10, 15), "Inspected; **no droppings**."),
                note(2, datetime(2026, 10, 4, 16, 0), "Day before: called ahead."),
                note(3, datetime(2026, 9, 20, 9, 0), "Weeks earlier, linked.", linked=True),
                note(4, datetime(2026, 9, 1, 9, 0), "Outside the window."),
                photo(11, datetime(2026, 10, 5, 10, 20), "trash room opening"),
                photo(12, datetime(2026, 10, 6, 8, 0), "next morning"),
                photo(13, datetime(2026, 10, 9, 8, 0), "too late"),
            ]
        )
        db.commit()


def _start(client, world, admin, template):
    resp = client.post(
        f"/v1/locations/{world.location_a}/service-reports",
        json={"template_id": template["id"], "service_order_id": str(world.service_order_a)},
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def run_task(task, data, **_):
        calls.append((task, data))
        return llm_tasks.TaskResult(
            output=task.output.model_validate(DRAFT),
            model="test/model",
            usage=Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150, cost=0.01),
            attempts=1,
        )

    monkeypatch.setattr(llm_tasks, "run_task", run_task)
    return calls


def test_starting_a_report_offers_notes_and_photos_near_the_work_date(
    client, world, admin, template, visit
):
    report = _start(client, world, admin, template)
    assert report["status"] == "draft" and report["revision"] == 1
    data = report["data"]
    notes = {n["pestpac_note_id"]: n["selected"] for n in data["notes"]}
    # On the day and linked-to-order are selected; the day before is offered; Sept 1 isn't.
    assert notes == {1: True, 2: False, 3: True}
    photos = {p["pestpac_document_id"]: (p["selected"], p["caption"]) for p in data["photos"]}
    assert photos == {11: (True, "trash room opening"), 12: (False, "next morning")}
    assert data["fields"] == {
        "summary": [],
        "sections": [],
        "recommendations": [],
        "distribution": "Leadership",
    }
    context = data["context"]
    assert context["service_order"]["work_date"].startswith("2026-10-05T09:30")
    assert context["service_order"]["service_number"] == 1
    assert context["location"]["pestpac_location_id"] == 800001
    assert [f["key"] for f in report["template_fields"]] == [f["key"] for f in FIELDS]


def test_drafting_sends_the_selected_notes_with_the_template_prompt(
    client, world, admin, template, visit, fake_llm
):
    report = _start(client, world, admin, template)
    resp = client.post(f"/v1/service-reports/{report['id']}/draft", headers=admin)
    assert resp.status_code == 202 and resp.json()["status"] == "drafting"
    _run_worker()

    [(task, data)] = fake_llm
    assert PROMPT in task.instructions
    assert "- sections (sections): Findings. One per area" in task.instructions
    assert "distribution" not in task.instructions  # not an LLM field
    assert set(task.output.model_fields) == {
        "summary",
        "sections",
        "recommendations",
        "findings",
    }
    assert "FINDINGS" in task.instructions and "- findings (object)" in task.instructions
    assert [n["text"] for n in data["notes"]] == [
        "Weeks earlier, linked.",
        "Inspected; **no droppings**.",
    ]
    assert data["service_order"]["pestpac_order_id"] is not None

    report = client.get(f"/v1/service-reports/{report['id']}", headers=admin).json()
    assert report["status"] == "draft" and report["draft_error"] is None
    assert report["data"]["fields"]["summary"] == DRAFT["summary"]
    assert report["data"]["fields"]["distribution"] == "Leadership"  # kept
    assert "findings" not in report["data"]["fields"]
    assert report["draft_usage"]["model"] == "test/model"


def _findings(world):
    with SessionLocal() as db:
        rows = db.query(InspectionFinding).all()
        return [
            (
                f.service_order_id,
                f.source,
                f.visit_type,
                f.rodent_activity,
                f.devices_serviced,
                f.model,
                [(i.kind, i.category, i.status, i.severity) for i in f.items],
            )
            for f in rows
        ]


def test_drafting_stores_the_visits_findings(client, world, admin, template, visit, fake_llm):
    report = _start(client, world, admin, template)
    client.post(f"/v1/service-reports/{report['id']}/draft", headers=admin)
    _run_worker()
    assert _findings(world) == [
        (
            world.service_order_a,
            "report_draft",
            "qc_inspection",
            "none",
            6,
            "test/model",
            [
                ("structural", "wall/floor gap", "open", None),
                ("pest", "gnats", None, "low"),
            ],
        )
    ]

    # Editing the narrative leaves them alone.
    url = f"/v1/service-reports/{report['id']}"
    resp = client.patch(url, json={"fields": {"summary": ["Rewritten."]}}, headers=admin)
    assert resp.status_code == 200
    assert len(_findings(world)[0][6]) == 2

    # A new draft replaces them: still one row for the order.
    again = {
        **DRAFT,
        "findings": {
            **DRAFT["findings"],
            "rodent_activity": "low",
            "structural_findings": [],
            "other_pests": [],
        },
    }
    fake_llm.clear()
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(DRAFT, "findings", again["findings"])
        client.post(f"{url}/draft", headers=admin)
        _run_worker()
    [row] = _findings(world)
    assert (row[3], row[6]) == ("low", [])


def test_drafting_needs_a_selected_note(client, world, admin, template):
    report = _start(client, world, admin, template)  # no notes near the work date
    resp = client.post(f"/v1/service-reports/{report['id']}/draft", headers=admin)
    assert resp.status_code == 422


def _comment_on_order(world, text="Sealed the gap by the back door."):
    with SessionLocal() as db:
        db.get(ServiceOrder, world.service_order_a).technician_comment = text
        db.commit()


def test_technician_comment_is_offered_selected_and_drafts_alone(
    client, world, admin, template, fake_llm
):
    _comment_on_order(world)
    report = _start(client, world, admin, template)  # no notes near the work date
    comment = report["data"]["technician_comment"]
    assert comment["text"] == "Sealed the gap by the back door." and comment["selected"] is True

    assert (
        client.post(f"/v1/service-reports/{report['id']}/draft", headers=admin).status_code == 202
    )
    _run_worker()
    [(_, data)] = fake_llm
    assert data["notes"] == []
    assert data["technician_comment"]["text"] == "Sealed the gap by the back door."


def test_deselected_technician_comment_is_not_sent(client, world, admin, template, visit, fake_llm):
    _comment_on_order(world)
    report = _start(client, world, admin, template)
    url = f"/v1/service-reports/{report['id']}"
    resp = client.patch(url, json={"technician_comment_selected": False}, headers=admin)
    assert resp.status_code == 200
    assert resp.json()["data"]["technician_comment"]["selected"] is False
    client.post(f"{url}/draft", headers=admin)
    _run_worker()
    [(_, data)] = fake_llm
    assert data["technician_comment"] is None and data["notes"]


def test_without_a_comment_there_is_nothing_to_select(client, world, admin, template):
    report = _start(client, world, admin, template)
    assert report["data"]["technician_comment"] is None
    resp = client.patch(
        f"/v1/service-reports/{report['id']}",
        json={"technician_comment_selected": True},
        headers=admin,
    )
    assert resp.status_code == 422


def test_an_llm_failure_is_recorded_on_the_report(
    client, world, admin, template, visit, monkeypatch
):
    def not_configured(task, data, **_):
        raise llm_tasks.LLMNotConfiguredError("OPENROUTER_API_KEY is not set")

    monkeypatch.setattr(llm_tasks, "run_task", not_configured)
    report = _start(client, world, admin, template)
    client.post(f"/v1/service-reports/{report['id']}/draft", headers=admin)
    _run_worker()
    report = client.get(f"/v1/service-reports/{report['id']}", headers=admin).json()
    assert report["status"] == "draft"
    assert report["draft_error"] == "OPENROUTER_API_KEY is not set"
    assert _findings(world) == []


def test_editing_checks_fields_and_photo_choices(client, world, admin, template, visit):
    report = _start(client, world, admin, template)
    url = f"/v1/service-reports/{report['id']}"

    wrong_type = client.patch(url, json={"fields": {"summary": "not a list"}}, headers=admin)
    assert wrong_type.status_code == 422
    unknown = client.patch(url, json={"fields": {"nope": "x"}}, headers=admin)
    assert unknown.status_code == 422
    photo_ids = [p["document_id"] for p in report["data"]["photos"]]
    partial = client.patch(
        url, json={"photos": [{"document_id": photo_ids[0], "selected": True}]}, headers=admin
    )
    assert partial.status_code == 422

    resp = client.patch(
        url,
        json={
            "fields": {"recommendations": ["Seal it."]},
            "photos": [
                {"document_id": photo_ids[1], "selected": True, "caption": "Morning after"},
                {"document_id": photo_ids[0], "selected": True, "caption": "Opening"},
            ],
            "notes": [{"note_id": report["data"]["notes"][0]["note_id"], "selected": False}],
        },
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["fields"]["recommendations"] == ["Seal it."]
    assert data["fields"]["distribution"] == "Leadership"
    assert [(p["pestpac_document_id"], p["caption"]) for p in data["photos"]] == [
        (12, "Morning after"),
        (11, "Opening"),
    ]
    assert data["notes"][0]["selected"] is False


def test_preview_renders_the_saved_data_with_embedded_photos(
    client, world, admin, template, visit, fake_llm
):
    report = _start(client, world, admin, template)
    client.post(f"/v1/service-reports/{report['id']}/draft", headers=admin)
    _run_worker()
    resp = client.get(f"/v1/service-reports/{report['id']}/preview", headers=admin)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert resp.headers["content-security-policy"] == "sandbox"
    html = resp.text
    assert "A <strong>quality control</strong> inspection" in html
    assert "<h2>Trash Room</h2>" in html
    assert 'src="data:image/jpeg;base64,' in html  # downscaled and embedded
    assert "<figcaption>trash room opening</figcaption>" in html
    assert "next morning" not in html  # offered but not selected


def test_finalizing_stores_the_pdf_and_locks_the_report(
    client, world, admin, template, visit, fake_llm, storage
):
    report = _start(client, world, admin, template)
    url = f"/v1/service-reports/{report['id']}"
    client.post(f"{url}/draft", headers=admin)
    _run_worker()

    final = client.post(f"{url}/finalize", headers=admin)
    assert final.status_code == 200, final.text
    final = final.json()
    assert final["status"] == "final" and final["has_pdf"] and final["finalized_at"]
    key = f"operators/{world.op_a}/reports/{report['id']}/r1.pdf"
    pdf, content_type = storage.objects[key]
    assert pdf.startswith(b"%PDF") and content_type == "application/pdf"
    assert final["pdf_size_bytes"] == len(pdf)

    download = client.get(f"{url}/pdf", headers=admin)
    assert download.status_code == 200 and download.content == pdf
    assert client.patch(url, json={"fields": {}}, headers=admin).status_code == 409
    assert client.post(f"{url}/draft", headers=admin).status_code == 409
    assert client.post(f"{url}/finalize", headers=admin).status_code == 409

    revision = client.post(f"{url}/revise", headers=admin)
    assert revision.status_code == 201
    revision = revision.json()
    assert (revision["revision"], revision["status"], revision["revises_id"]) == (
        2,
        "draft",
        report["id"],
    )
    assert revision["data"]["fields"] == final["data"]["fields"]
    assert (
        client.post(f"/v1/service-reports/{revision['id']}/revise", headers=admin).status_code
        == 409
    )


def test_only_the_newest_version_is_final(client, world, admin, template, visit, storage):
    first = _start(client, world, admin, template)
    v1 = f"/v1/service-reports/{first['id']}"
    assert client.post(f"{v1}/finalize", headers=admin).status_code == 200

    second = client.post(f"{v1}/revise", headers=admin).json()
    v2 = f"/v1/service-reports/{second['id']}"
    # One draft version at a time, and only the latest version can be revised.
    assert client.post(f"{v1}/revise", headers=admin).status_code == 409
    assert client.get(v1, headers=admin).json()["latest_id"] == second["id"]
    # Until the new version is final, the earlier one stays final.
    assert client.get(v1, headers=admin).json()["status"] == "final"

    assert client.post(f"{v2}/finalize", headers=admin).status_code == 200
    old = client.get(v1, headers=admin).json()
    assert old["status"] == "superseded" and old["has_pdf"]  # its PDF is kept
    assert client.get(f"{v1}/pdf", headers=admin).status_code == 200
    assert client.patch(v1, json={"fields": {}}, headers=admin).status_code == 409
    assert client.post(f"{v1}/revise", headers=admin).status_code == 409

    third = client.post(f"{v2}/revise", headers=admin).json()
    assert third["revision"] == 3 and third["revises_id"] == second["id"]
    listed = client.get(f"/v1/locations/{world.location_a}/service-reports", headers=admin).json()
    mine = {
        r["id"]: r["status"] for r in listed if r["service_order_id"] == first["service_order_id"]
    }
    assert mine == {first["id"]: "superseded", second["id"]: "final", third["id"]: "draft"}


def test_a_photo_not_stored_yet_blocks_the_render(client, world, admin, template, storage):
    with SessionLocal() as db:
        db.add(
            Document(
                operator_id=world.op_a,
                document_type="LocationDocument",
                pestpac_document_id=21,
                name="unstored",
                file_name="unstored.jpg",
                document_date=datetime(2026, 10, 5, 11, 0),
                location_id=world.location_a,
                pestpac_fetched_at=datetime.now(UTC),
            )
        )
        db.commit()
    report = _start(client, world, admin, template)
    assert report["data"]["photos"][0]["selected"]
    resp = client.get(f"/v1/service-reports/{report['id']}/preview", headers=admin)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Photo 21 isn't stored yet"


def test_location_lists_its_reports(client, world, admin, template):
    _start(client, world, admin, template)
    listed = client.get(f"/v1/locations/{world.location_a}/service-reports", headers=admin).json()
    names = sorted(r["template_name"] for r in listed)
    assert names == ["Service report", "Service summary", "Service summary"]


def test_template_fields_are_validated_and_versioned(client, world, template):
    platform = headers_for(client, world.emails["platform_admin"])
    url = f"/v1/report-templates/{template['id']}"
    duplicate = FIELDS + [FIELDS[0]]
    assert client.patch(url, json={"fields": duplicate}, headers=platform).status_code == 422
    # Drafting's reply carries the visit's findings under "findings".
    reserved = FIELDS + [{"key": "findings", "label": "Findings", "type": "text"}]
    assert client.patch(url, json={"fields": reserved}, headers=platform).status_code == 422
    # The HTML uses fields.summary; dropping the field fails the sample render.
    resp = client.patch(url, json={"fields": FIELDS[1:]}, headers=platform)
    assert resp.status_code == 422 and "summary" in resp.json()["detail"]
    bumped = client.patch(url, json={"prompt": PROMPT + " Be brief."}, headers=platform).json()
    assert bumped["version"] == 2


def test_an_order_has_one_report_whatever_the_template(client, world, admin, template):
    _start(client, world, admin, template)
    for template_id in (template["id"], str(world.report_template_a)):
        resp = client.post(
            f"/v1/locations/{world.location_a}/service-reports",
            json={"template_id": template_id, "service_order_id": str(world.service_order_a)},
            headers=admin,
        )
        assert resp.status_code == 409
        assert "already has a report" in resp.json()["detail"]


def test_starting_needs_the_locations_own_order_and_template(client, world, admin, template):
    resp = client.post(
        f"/v1/locations/{world.location_a}/service-reports",
        json={"template_id": template["id"], "service_order_id": str(world.location_a)},
        headers=admin,
    )
    assert resp.status_code == 404


def test_posted_orders_name_their_report(client, world, admin, template):
    with SessionLocal() as db:
        order = db.get(ServiceOrder, world.service_order_a)
        order.posted = True
        db.commit()
    report = _start(client, world, admin, template)
    page = client.get(f"/v1/companies/{world.company_a}/posted-service-orders", headers=admin)
    [item] = [i for i in page.json()["items"] if i["id"] == str(world.service_order_a)]
    assert item["report_id"] == report["id"]
