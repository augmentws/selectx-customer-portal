"""Every endpoint × every actor. 404 means "can't see it" (existence hidden), 403 means "can see
it but lacks the permission". Backend authorization is the final word, so this is the
contract the UI's permission checks mirror."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from tests.conftest import ACTORS, World, headers_for

PA, AA, SA, AB, NR, MA = ACTORS  # platform_admin, admin_a, staff_a, admin_b, no_role, manager_a


@dataclass(frozen=True)
class Case:
    name: str
    method: str
    path: Callable[[World], str]
    expected: dict[str, int]
    body: Callable[[World], Any] | None = None


def _all(status: int, **overrides: int) -> dict[str, int]:
    return {actor: overrides.get(actor, status) for actor in ACTORS}


CASES = [
    # A company user (manager_a) sees only company A and its dashboard: 404 everywhere else, and
    # 403 on routes open to anyone who can see an operator.
    Case("list operators", "GET", lambda w: "/v1/operators", _all(200, no_role=403, manager_a=403)),
    # Search is open to anyone who can see an operator; results are scoped (tests/test_search.py).
    Case("search", "GET", lambda w: "/v1/search?q=acme", _all(200, no_role=403, manager_a=403)),
    Case(
        "create operator",
        "POST",
        lambda w: "/v1/operators",
        _all(403, platform_admin=201),
        lambda w: {"name": "New Op", "slug": "new-op", "pestpac_tenant_id": "330000"},
    ),
    Case(
        "get operator A",
        "GET",
        lambda w: f"/v1/operators/{w.op_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "update operator A",
        "PATCH",
        lambda w: f"/v1/operators/{w.op_a}",
        _all(404, platform_admin=200, admin_a=403, staff_a=403),
        lambda w: {"name": "Renamed"},
    ),
    Case(
        "list companies of A",
        "GET",
        lambda w: f"/v1/operators/{w.op_a}/companies",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "create company in A",
        "POST",
        lambda w: f"/v1/operators/{w.op_a}/companies",
        _all(404, platform_admin=201, admin_a=201, staff_a=403),
        lambda w: {"name": "Gamma Foods"},
    ),
    Case(
        "get company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200, manager_a=200),
    ),
    Case(
        "update company A",
        "PATCH",
        lambda w: f"/v1/companies/{w.company_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
        lambda w: {"name": "Acme Restaurants Inc"},
    ),
    Case(
        "list bill-tos of company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/bill-tos",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "onboard bill-to to company A",
        "POST",
        lambda w: f"/v1/companies/{w.company_a}/bill-tos",
        _all(404, platform_admin=201, admin_a=201, staff_a=403),
        lambda w: {"pestpac_bill_to_id": 180020, "name": "Acme Northeast"},
    ),
    Case(
        "look up a PestPac bill-to for company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/bill-tos/lookup?pestpac_bill_to_id=180020",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "refresh bill-to A from PestPac",
        "POST",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}/refresh",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "list locations of bill-to A",
        "GET",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}/locations",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list service orders of bill-to A",
        "GET",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}/service-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list posted service orders of bill-to A",
        "GET",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}/posted-service-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list locations of company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/locations",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list posted service orders of company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/posted-service-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list open service orders of bill-to A",
        "GET",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}/open-service-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list open service orders of company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/open-service-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list posted service orders of a location in A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/posted-service-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list invoiced service orders of a location in A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/invoiced-service-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "list open service orders of a location in A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/open-service-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list invoices of a location in A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/invoices",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "list invoiced orders of bill-to A",
        "GET",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}/invoiced-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "list invoiced orders of company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/invoiced-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "list GoCanvas requests of operator A",
        "GET",
        lambda w: f"/v1/operators/{w.op_a}/gocanvas-requests",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "get GoCanvas request A",
        "GET",
        lambda w: f"/v1/gocanvas-requests/{w.gocanvas_request_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "get invoice A",
        "GET",
        lambda w: f"/v1/invoices/{w.invoice_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "sync service orders of bill-to A",
        "POST",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}/service-orders/sync",
        _all(404, platform_admin=202, admin_a=202, staff_a=403),
    ),
    Case(
        "list sync jobs of bill-to A",
        "GET",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}/sync-jobs",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list service orders of a location in A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/service-orders",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "sync service orders of a location in A",
        "POST",
        lambda w: f"/v1/locations/{w.location_a}/service-orders/sync",
        _all(404, platform_admin=202, admin_a=202, staff_a=403),
    ),
    Case(
        "get a location in A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list notes of a location in A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/notes",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "get a service order of A",
        "GET",
        lambda w: f"/v1/service-orders/{w.service_order_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list notes of a service order of A",
        "GET",
        lambda w: f"/v1/service-orders/{w.service_order_a}/notes",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list related items of a service order of A",
        "GET",
        lambda w: f"/v1/service-orders/{w.service_order_a}/related",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "get a sync job of A",
        "GET",
        lambda w: f"/v1/sync-jobs/{w.sync_job_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "get bill-to A",
        "GET",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "update bill-to A",
        "PATCH",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
        lambda w: {"description": "Covers HQ only"},
    ),
    Case(
        "list members of A",
        "GET",
        lambda w: f"/v1/tenants/{w.op_a}/members",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "add member to A",
        "POST",
        lambda w: f"/v1/tenants/{w.op_a}/members",
        _all(404, platform_admin=201, admin_a=201, staff_a=403),
        lambda w: {
            "email": "new.staff@test.example",
            "role": "operator_staff",
            "temporary_password": "temporary-password-1",
        },
    ),
    Case(
        "change staff_a's role in A",
        "PATCH",
        lambda w: f"/v1/tenants/{w.op_a}/members/{w.user_ids['staff_a']}",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
        lambda w: {"role": "operator_admin"},
    ),
    Case(
        "remove staff_a from A",
        "DELETE",
        lambda w: f"/v1/tenants/{w.op_a}/members/{w.user_ids['staff_a']}",
        _all(404, platform_admin=204, admin_a=204, staff_a=403),
    ),
    Case(
        "list members of company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/members",
        _all(404, platform_admin=200, admin_a=200, staff_a=403, manager_a=403),
    ),
    Case(
        "add member to company A",
        "POST",
        lambda w: f"/v1/companies/{w.company_a}/members",
        _all(404, platform_admin=201, admin_a=201, staff_a=403, manager_a=403),
        lambda w: {
            "email": "new.customer@test.example",
            "role": "company_manager",
            "temporary_password": "temporary-password-1",
        },
    ),
    Case(
        "change manager_a's role in company A",
        "PATCH",
        lambda w: f"/v1/companies/{w.company_a}/members/{w.user_ids['manager_a']}",
        _all(404, platform_admin=200, admin_a=200, staff_a=403, manager_a=403),
        lambda w: {"role": "company_manager"},
    ),
    Case(
        "remove manager_a from company A",
        "DELETE",
        lambda w: f"/v1/companies/{w.company_a}/members/{w.user_ids['manager_a']}",
        _all(404, platform_admin=204, admin_a=204, staff_a=403, manager_a=403),
    ),
    Case(
        "list platform members",
        "GET",
        lambda w: f"/v1/tenants/{w.platform_id}/members",
        _all(404, platform_admin=200),
    ),
    Case(
        "add platform admin",
        "POST",
        lambda w: f"/v1/tenants/{w.platform_id}/members",
        _all(404, platform_admin=201),
        lambda w: {
            "email": "second.admin@test.example",
            "role": "platform_admin",
            "temporary_password": "temporary-password-1",
        },
    ),
    Case(
        "get PestPac connection of A",
        "GET",
        lambda w: f"/v1/operators/{w.op_a}/pestpac-connection",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "save PestPac connection of A",
        "PUT",
        lambda w: f"/v1/operators/{w.op_a}/pestpac-connection",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
        lambda w: {"client_id": "client-a", "username": "api-user-a"},
    ),
    Case(
        "verify PestPac connection of A",
        "POST",
        lambda w: f"/v1/operators/{w.op_a}/pestpac-connection/verify",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "get GoCanvas connection of A",
        "GET",
        lambda w: f"/v1/operators/{w.op_a}/gocanvas-connection",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "save GoCanvas connection of A",
        "PUT",
        lambda w: f"/v1/operators/{w.op_a}/gocanvas-connection",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
        lambda w: {"client_id": "client-a", "client_secret": "secret-a"},
    ),
    Case(
        "verify GoCanvas connection of A",
        "POST",
        lambda w: f"/v1/operators/{w.op_a}/gocanvas-connection/verify",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "list risk inspections of company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/risk-inspections",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list risk inspections of location A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/risk-inspections",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "get risk inspection A",
        "GET",
        lambda w: f"/v1/risk-inspections/{w.risk_inspection_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "get stored file of company A",
        "GET",
        lambda w: f"/v1/files/{w.file_a}",
        # Company users hold no files:read yet, so company A's manager can't open it.
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list documents of location A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/documents",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list conditions of location A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/conditions",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "get document file of A",
        "GET",
        lambda w: f"/v1/documents/{w.document_a}/file",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "sync locations of bill-to A",
        "POST",
        lambda w: f"/v1/bill-tos/{w.bill_to_a}/locations/sync",
        _all(404, platform_admin=202, admin_a=202, staff_a=403),
    ),
    Case(
        "sync location A",
        "POST",
        lambda w: f"/v1/locations/{w.location_a}/sync",
        _all(404, platform_admin=202, admin_a=202, staff_a=403),
    ),
    Case(
        "list service reports of location A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/service-reports",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "start a service report at location A",
        "POST",
        lambda w: f"/v1/locations/{w.location_a}/service-reports",
        _all(404, platform_admin=201, admin_a=201, staff_a=403),
        lambda w: {
            "template_id": str(w.report_template_a),
            "service_order_id": str(w.service_order_a),
        },
    ),
    Case(
        "get service report A",
        "GET",
        lambda w: f"/v1/service-reports/{w.report_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "edit service report A",
        "PATCH",
        lambda w: f"/v1/service-reports/{w.report_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
        lambda w: {"fields": {}},
    ),
    Case(
        "draft service report A",
        "POST",
        lambda w: f"/v1/service-reports/{w.report_a}/draft",
        _all(404, platform_admin=202, admin_a=202, staff_a=403),
    ),
    Case(
        "preview service report A",
        "GET",
        lambda w: f"/v1/service-reports/{w.report_a}/preview",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "finalize service report A",
        "POST",
        lambda w: f"/v1/service-reports/{w.report_a}/finalize",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "revise final service report A",
        "POST",
        lambda w: f"/v1/service-reports/{w.report_final_a}/revise",
        _all(404, platform_admin=201, admin_a=201, staff_a=403),
    ),
    Case(
        "get PDF of final service report A",
        "GET",
        lambda w: f"/v1/service-reports/{w.report_final_a}/pdf",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "list webhook events of A",
        "GET",
        lambda w: f"/v1/operators/{w.op_a}/webhook-events",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "get webhook event of A",
        "GET",
        lambda w: f"/v1/webhook-events/{w.webhook_event_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=403),
    ),
    Case(
        "dashboard of company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/dashboard",
        _all(404, platform_admin=200, admin_a=200, staff_a=200, manager_a=200),
    ),
    Case(
        "list report templates of company A",
        "GET",
        lambda w: f"/v1/companies/{w.company_a}/report-templates",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "create report template in company A",
        "POST",
        lambda w: f"/v1/companies/{w.company_a}/report-templates",
        _all(404, platform_admin=201, admin_a=403, staff_a=403),
        lambda w: {"name": "Visit report", "html": "<p>{{ location.city }}</p>"},
    ),
    Case(
        "get report template A",
        "GET",
        lambda w: f"/v1/report-templates/{w.report_template_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "update report template A",
        "PATCH",
        lambda w: f"/v1/report-templates/{w.report_template_a}",
        _all(404, platform_admin=200, admin_a=403, staff_a=403),
        lambda w: {"name": "Renamed report"},
    ),
    Case(
        "generate report for location A",
        "GET",
        lambda w: f"/v1/locations/{w.location_a}/reports/{w.report_template_a}",
        _all(404, platform_admin=200, admin_a=200, staff_a=200),
    ),
    Case(
        "preview report for location A",
        "POST",
        lambda w: f"/v1/locations/{w.location_a}/report-preview",
        _all(404, platform_admin=200, admin_a=403, staff_a=403),
        lambda w: {"html": "<p>{{ location.name }}</p>"},
    ),
    Case(
        "list roles",
        "GET",
        lambda w: "/v1/roles",
        _all(200, staff_a=403, no_role=403, manager_a=403),
    ),
    Case(
        "list permissions",
        "GET",
        lambda w: "/v1/permissions",
        _all(200, staff_a=403, no_role=403, manager_a=403),
    ),
]


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_access(client, world, pestpac, case: Case, actor: str):
    headers = headers_for(client, world.emails[actor])
    body = case.body(world) if case.body else None
    resp = client.request(case.method, case.path(world), json=body, headers=headers)
    assert resp.status_code == case.expected[actor], (
        f"{actor} {case.method} {case.name}: {resp.status_code} {resp.text}"
    )


def test_every_v1_route_is_in_the_matrix():
    """Adding an endpoint without deciding who may call it should fail loudly."""
    from app.main import app

    covered = {(c.method, c.path(_PLACEHOLDER_WORLD)) for c in CASES}
    covered_templates = {(m, _template(p)) for m, p in covered}
    exempt = {
        ("POST", "/v1/auth/login"),
        ("POST", "/v1/auth/refresh"),
        ("POST", "/v1/auth/logout"),
        ("POST", "/v1/auth/password"),
        ("GET", "/v1/auth/me"),
        # Public: PestPac and GoCanvas hold no session (tests/test_webhooks.py, test_gocanvas.py).
        ("POST", "/v1/webhooks/pestpac"),
        ("POST", "/v1/webhooks/gocanvas/{operator_id}"),
    }
    routes = {
        (method.upper(), path)
        for path, ops in app.openapi()["paths"].items()
        if path.startswith("/v1/")
        for method in ops
    }
    missing = routes - covered_templates - exempt
    assert not missing, f"routes without access-matrix coverage: {sorted(missing)}"


_PLACEHOLDER_WORLD = World(
    platform_id="{tenant_id}",  # type: ignore[arg-type]
    op_a="{operator_id}",  # type: ignore[arg-type]
    op_b="{operator_id}",  # type: ignore[arg-type]
    company_a="{company_id}",  # type: ignore[arg-type]
    bill_to_a="{bill_to_id}",  # type: ignore[arg-type]
    company_b="{company_id}",  # type: ignore[arg-type]
    emails={},
    user_ids={actor: "{user_id}" for actor in ACTORS},  # type: ignore[misc]
    location_a="{location_id}",  # type: ignore[arg-type]
    sync_job_a="{job_id}",  # type: ignore[arg-type]
    service_order_a="{order_id}",  # type: ignore[arg-type]
    report_template_a="{template_id}",  # type: ignore[arg-type]
    webhook_event_a="{event_id}",  # type: ignore[arg-type]
    invoice_a="{invoice_id}",  # type: ignore[arg-type]
    gocanvas_request_a="{request_id}",  # type: ignore[arg-type]
    document_a="{document_id}",  # type: ignore[arg-type]
    file_a="{file_id}",  # type: ignore[arg-type]
    risk_inspection_a="{inspection_id}",  # type: ignore[arg-type]
    report_a="{report_id}",  # type: ignore[arg-type]
    report_final_a="{report_id}",  # type: ignore[arg-type]
)


def _template(path: str) -> str:
    # Members routes use {tenant_id} for both platform and operator tenants.
    path = path.replace("/tenants/{operator_id}/", "/tenants/{tenant_id}/")
    return path.split("?", 1)[0]
