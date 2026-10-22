import base64
from urllib import request

import pytest

from app.db.session import SessionLocal
from app.models import Location, ReportTemplate
from app.services import reports
from tests.conftest import headers_for

# 1x1 transparent PNG.
PIXEL = base64.b64encode(
    bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
    )
).decode()


@pytest.fixture
def admin(client, world):
    return headers_for(client, world.emails["platform_admin"])


def _create(client, world, admin, html: str, name: str = "Visit report"):
    return client.post(
        f"/v1/companies/{world.company_a}/report-templates",
        json={"name": name, "html": html},
        headers=admin,
    )


def test_generated_report_is_a_pdf_download(client, world):
    staff = headers_for(client, world.emails["staff_a"])
    resp = client.get(
        f"/v1/locations/{world.location_a}/reports/{world.report_template_a}", headers=staff
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert (
        resp.headers["content-disposition"] == 'attachment; filename="Service-summary-800001.pdf"'
    )
    assert resp.content.startswith(b"%PDF")


def test_templates_see_the_location_data(world):
    html = (
        "{{ operator.name }}|{{ company.name }}|{{ bill_to.name }}|"
        "{{ location.name }}|{{ location.pestpac_location_id }}|{{ generated_at.year }}"
    )
    with SessionLocal() as db:
        location = db.get(Location, world.location_a)
        rendered = reports.render_html(html, reports.build_context(db, location))
    operator, company, bill_to, name, location_id, year = rendered.split("|")
    assert (operator, company, bill_to, name) == (
        "Operator A",
        "Acme Restaurants",
        "Acme HQ",
        "ACME TACOS - STORE #1",
    )
    assert location_id == "800001" and int(year) >= 2026


def test_values_are_html_escaped():
    context = reports.sample_context()
    context.location.name = "<script>alert(1)</script>"
    assert reports.render_html("{{ location.name }}", context) == (
        "&lt;script&gt;alert(1)&lt;/script&gt;"
    )


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ("<p>{{ location.nickname }}</p>", "UndefinedError"),
        ("<p>{{ customer.name }}</p>", "UndefinedError"),
        ("<p>{% if %}</p>", "TemplateSyntaxError on line 1"),
        ("<p>{{ 1 / 0 }}</p>", "ZeroDivisionError"),
        # The sandbox hides Python internals.
        ("{{ ''.__class__.__mro__ }}", "SecurityError"),
        ("{{ location.__class__ }}", "SecurityError"),
    ],
)
def test_broken_templates_are_rejected_on_save(client, world, admin, html, message):
    resp = _create(client, world, admin, html)
    assert resp.status_code == 422
    assert message in resp.json()["detail"]


def test_version_increments_only_when_html_changes(client, world, admin):
    created = _create(client, world, admin, "<p>{{ location.city }}</p>").json()
    assert created["version"] == 1
    url = f"/v1/report-templates/{created['id']}"
    assert client.patch(url, json={"name": "Renamed"}, headers=admin).json()["version"] == 1
    same = client.patch(url, json={"html": "<p>{{ location.city }}</p>"}, headers=admin)
    assert same.json()["version"] == 1
    changed = client.patch(url, json={"html": "<p>{{ location.zip }}</p>"}, headers=admin)
    assert changed.json()["version"] == 2


def test_broken_html_on_update_keeps_the_saved_version(client, world, admin):
    url = f"/v1/report-templates/{world.report_template_a}"
    resp = client.patch(url, json={"html": "{{ nope }}"}, headers=admin)
    assert resp.status_code == 422
    assert "{{ company.name }}" in client.get(url, headers=admin).json()["html"]


def test_only_the_locations_own_active_templates_render(client, world, admin):
    other = client.post(
        f"/v1/companies/{world.company_b}/report-templates",
        json={"name": "Other customer", "html": "<p>x</p>"},
        headers=admin,
    ).json()
    url = f"/v1/locations/{world.location_a}/reports/{other['id']}"
    assert client.get(url, headers=admin).status_code == 404

    client.patch(
        f"/v1/report-templates/{world.report_template_a}", json={"is_active": False}, headers=admin
    )
    url = f"/v1/locations/{world.location_a}/reports/{world.report_template_a}"
    assert client.get(url, headers=admin).status_code == 404


def test_inactive_templates_are_listed_only_on_request(client, world, admin):
    client.patch(
        f"/v1/report-templates/{world.report_template_a}", json={"is_active": False}, headers=admin
    )
    url = f"/v1/companies/{world.company_a}/report-templates"
    assert client.get(url, headers=admin).json() == []
    assert len(client.get(f"{url}?include_inactive=true", headers=admin).json()) == 1


def test_preview_renders_unsaved_html(client, world, admin):
    resp = client.post(
        f"/v1/locations/{world.location_a}/report-preview",
        json={"html": "<p>{{ location.name }}</p>"},
        headers=admin,
    )
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    with SessionLocal() as db:
        assert db.query(ReportTemplate).count() == 1  # nothing saved


def test_only_data_uris_are_fetched(monkeypatch):
    opened: list[str] = []
    original = request.OpenerDirector.open

    def spy(self, url, *args, **kwargs):
        opened.append(url if isinstance(url, str) else url.full_url)
        return original(self, url, *args, **kwargs)

    monkeypatch.setattr(request.OpenerDirector, "open", spy)
    pdf = reports.html_to_pdf(
        f'<img src="data:image/png;base64,{PIXEL}">'
        '<img src="http://169.254.169.254/latest/meta-data">'
        '<img src="file:///etc/passwd">'
        '<link rel="stylesheet" href="https://example.com/style.css">'
    )
    assert pdf.startswith(b"%PDF")
    assert opened and all(url.startswith("data:") for url in opened)
