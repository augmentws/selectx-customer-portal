import os
from dataclasses import dataclass

from dotenv import dotenv_values

# Point the app at the dedicated test database before anything imports settings.
_env = {**dotenv_values(".env"), **os.environ}
TEST_DATABASE_URL = _env.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://customer_portal:customer_portal@localhost:5433/customer_portal_test",
)
TEST_DB_NAME = "customer_portal_test"
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 32)
# Fixed test-only Fernet key so ciphertext written by fixtures stays readable.
os.environ["APP_ENCRYPTION_KEYS"] = "Q2PYvKXuaXz5O3b4pV3-6dmgHAx5k5hvYb7Qm9H8u2Y="
os.environ["PESTPAC_DEBUG_BODIES"] = "false"

import json  # noqa: E402
import re  # noqa: E402
import uuid  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
import responses  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    BillTo,
    Company,
    ConnectionStatus,
    Location,
    Membership,
    PestPacConnection,
    ServiceOrder,
    SyncJob,
    SyncJobKind,
    SyncJobStatus,
    Tenant,
    TenantKind,
)
from app.security.permissions import SystemRole  # noqa: E402
from app.security.secrets import encrypt  # noqa: E402
from app.services import pestpac_connection  # noqa: E402
from app.services.auth import create_user  # noqa: E402
from app.services.rbac import get_platform_tenant, get_system_role  # noqa: E402

PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="session", autouse=True)
def _database():
    with engine.connect() as conn:
        current = conn.execute(text("SELECT current_database()")).scalar_one()
    assert current == TEST_DB_NAME, f"refusing to run tests against {current!r}"

    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    # Keep migration seed data (permissions, system roles, platform tenant).
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE webhook_events, notes, sync_jobs, service_orders, technicians, "
                "locations, pestpac_connections, bill_tos, companies, memberships, "
                "auth_sessions, credentials, users"
            )
        )
        conn.execute(text("DELETE FROM roles WHERE tenant_id IS NOT NULL"))
        conn.execute(text("DELETE FROM tenants WHERE kind <> 'platform'"))
    pestpac_connection._clients.clear()


PESTPAC_BASE = get_settings().pestpac_default_base_url
PESTPAC_TOKEN_URL = get_settings().pestpac_token_url
KNOWN_BILL_TO_IDS = {175101, 180020}
# Sample GET /BillTos/{id} response with personal details replaced.
BILL_TO_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "pestpac_bill_to.json").read_text()
)


def pestpac_bill_to_body(bill_to_id: int, **overrides) -> dict:
    return {**BILL_TO_FIXTURE, "BillToID": bill_to_id, **overrides}


# Sample GET /BillTos/{id}/locations/pageable items, with personal details replaced.
LOCATIONS_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "pestpac_locations.json").read_text()
)


def pestpac_locations(bill_to_id: int, items: list[dict] | None = None) -> list[dict]:
    """Locations for a bill-to: the fixture by default, re-parented to `bill_to_id`."""
    return [
        {**item, "BillToID": bill_to_id}
        for item in (items if items is not None else LOCATIONS_FIXTURE)
    ]


# Sample service order (GET /ServiceOrders/{id} item), with the tech's username replaced.
SERVICE_ORDER_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "pestpac_service_order.json").read_text()
)


def pestpac_order(order_id: int, location_id: int, bill_to_id: int, **overrides) -> dict:
    return {
        **SERVICE_ORDER_FIXTURE,
        "OrderID": order_id,
        "LocationID": location_id,
        "BillToID": bill_to_id,
        **overrides,
    }


# Sample GET /lookups/Employees/technicians/{techId} record, with personal details replaced.
TECHNICIAN_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "pestpac_technician.json").read_text()
)
TECHNICIAN_URL = re.compile(re.escape(PESTPAC_BASE) + r"/lookups/Employees/technicians/(\d+)$")

TECHNICIANS_URL = re.compile(re.escape(PESTPAC_BASE) + r"/lookups/Employees/technicians$")
LOCATION_NOTES_URL = re.compile(re.escape(PESTPAC_BASE) + r"/Locations/(\d+)/notes")
NOTE_URL = re.compile(re.escape(PESTPAC_BASE) + r"/Notes/(\d+)$")


def pestpac_note(note_id: int, *, code="SERVICE", text="Service: RAMP MONITOR", user="TECH01"):
    """A GET /Locations/{id}/notes item (no associations)."""
    return {
        "NoteID": note_id,
        "BillToID": None,
        "LocationID": None,
        "NoteDate": "2026-10-14T03:43:24",
        "NoteCode": code,
        "Note": text,
        "CreatedByUser": user,
        "AlertExpirationDate": None,
        "ShowOnPortal": False,
        "WWID": None,
        "NoteOriginType": None,
    }


def pestpac_note_detail(item: dict, *, location_id=None, order_id=None, invoice_id=None) -> dict:
    """GET /Notes/{id} for a list item, with its associations."""
    detail = {
        k: v for k, v in item.items() if k not in ("BillToID", "LocationID", "NoteOriginType")
    }
    detail["Associations"] = {
        "LocationID": location_id,
        "ContactID": None,
        "BillToID": None,
        "TaskID": None,
        "OrderID": order_id,
        "SalesLeadID": None,
        "InvoiceID": invoice_id,
        "CallID": None,
    }
    return detail


LOCATION_ORDERS_URL = re.compile(re.escape(PESTPAC_BASE) + r"/Locations/(\d+)/serviceOrders$")
SERVICE_ORDER_URL = re.compile(re.escape(PESTPAC_BASE) + r"/ServiceOrders/(\d+)$")


LOCATIONS_URL = re.compile(re.escape(PESTPAC_BASE) + r"/BillTos/(\d+)/locations/pageable")


def locations_callback(pages_by_bill_to: dict[int, list[dict]] | None = None):
    """A `responses` callback serving locations with real skip/take paging."""

    def callback(request):
        from urllib.parse import parse_qs, urlparse

        url = urlparse(request.url)
        bill_to_id = int(LOCATIONS_URL.search(request.url).group(1))
        query = parse_qs(url.query)
        skip, take = int(query["skip"][0]), int(query["take"][0])
        items = (pages_by_bill_to or {}).get(bill_to_id, pestpac_locations(bill_to_id))
        return 200, {}, json.dumps(items[skip : skip + take])

    return callback


COMPANY_SETUP = {"CompanyID": 1, "Company": "Select Exterminating", "Settings": {}}


@pytest.fixture
def pestpac():
    """Mocked PestPac: token, /CompanySetup, and /BillTos/{id} (known ids 200, others 404).
    Any other outbound HTTP fails the test."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.post(PESTPAC_TOKEN_URL, json={"access_token": "test-token"})
        rsps.get(f"{PESTPAC_BASE}/CompanySetup", json=COMPANY_SETUP)

        def bill_to(request):
            bill_to_id = int(request.url.rstrip("/").rsplit("/", 1)[-1])
            if bill_to_id in KNOWN_BILL_TO_IDS:
                return 200, {}, json.dumps(pestpac_bill_to_body(bill_to_id))
            return 404, {}, "{}"

        rsps.add_callback(
            responses.GET, re.compile(re.escape(PESTPAC_BASE) + r"/BillTos/\d+$"), bill_to
        )
        rsps.add_callback(responses.GET, LOCATIONS_URL, locations_callback())

        # Open orders per PestPac LocationID; tests set entries (a list, or an int status).
        rsps.orders_by_location = {}

        def location_orders(request):
            location_id = int(LOCATION_ORDERS_URL.search(request.url).group(1))
            value = rsps.orders_by_location.get(location_id, [])
            if isinstance(value, int):
                return value, {}, "{}"
            return 200, {}, json.dumps(value)

        def single_order(request):
            order_id = int(SERVICE_ORDER_URL.search(request.url).group(1))
            for orders in rsps.orders_by_location.values():
                if isinstance(orders, list):
                    for order in orders:
                        if order["OrderID"] == order_id:
                            return 200, {}, json.dumps(order)
            return 404, {}, "{}"

        # Technicians PestPac knows, by TechID; others 404.
        rsps.technicians = {TECHNICIAN_FIXTURE["TechID"]: TECHNICIAN_FIXTURE}

        def technician(request):
            tech_id = int(TECHNICIAN_URL.search(request.url).group(1))
            body = rsps.technicians.get(tech_id)
            return (200, {}, json.dumps(body)) if body else (404, {}, "{}")

        rsps.add_callback(responses.GET, TECHNICIAN_URL, technician)
        # The seeding list: by default everyone in rsps.technicians. Tests can set a list
        # (e.g. []) or an int status code.
        rsps.technicians_listed = None

        def technicians_list(request):
            listed = rsps.technicians_listed
            if isinstance(listed, int):
                return listed, {}, "{}"
            body = list(rsps.technicians.values()) if listed is None else listed
            return 200, {}, json.dumps(body)

        rsps.add_callback(responses.GET, TECHNICIANS_URL, technicians_list)

        # Notes: list items per PestPac LocationID (paged), and details by NoteID.
        rsps.notes_by_location = {}
        rsps.note_details = {}

        def location_notes(request):
            from urllib.parse import parse_qs, urlparse

            location_id = int(LOCATION_NOTES_URL.search(request.url).group(1))
            query = parse_qs(urlparse(request.url).query)
            skip, take = int(query["skip"][0]), int(query["take"][0])
            value = rsps.notes_by_location.get(location_id, [])
            if isinstance(value, int):
                return value, {}, "{}"
            return 200, {}, json.dumps(value[skip : skip + take])

        def note_detail(request):
            note_id = int(NOTE_URL.search(request.url).group(1))
            body = rsps.note_details.get(note_id)
            return (200, {}, json.dumps(body)) if body else (404, {}, "{}")

        rsps.add_callback(responses.GET, LOCATION_NOTES_URL, location_notes)
        rsps.add_callback(responses.GET, NOTE_URL, note_detail)
        rsps.add_callback(responses.GET, LOCATION_ORDERS_URL, location_orders)
        rsps.add_callback(responses.GET, SERVICE_ORDER_URL, single_order)
        yield rsps


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def headers_for(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    resp = login(client, email, password)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@dataclass
class World:
    """Two operators, users holding each role, and one company with a bill-to in operator A."""

    platform_id: uuid.UUID
    op_a: uuid.UUID
    op_b: uuid.UUID
    company_a: uuid.UUID
    bill_to_a: uuid.UUID
    company_b: uuid.UUID
    emails: dict[str, str]
    user_ids: dict[str, uuid.UUID]
    location_a: uuid.UUID
    sync_job_a: uuid.UUID
    service_order_a: uuid.UUID


ACTORS = ("platform_admin", "admin_a", "staff_a", "admin_b", "no_role")


@pytest.fixture
def world() -> World:
    with SessionLocal() as db:
        platform = get_platform_tenant(db)
        op_a = Tenant(
            parent_id=platform.id,
            kind=TenantKind.operator,
            name="Operator A",
            slug="op-a",
            pestpac_tenant_id="115060",
        )
        op_b = Tenant(
            parent_id=platform.id,
            kind=TenantKind.operator,
            name="Operator B",
            slug="op-b",
            pestpac_tenant_id="220000",
        )
        db.add_all([op_a, op_b])
        db.flush()

        emails = {actor: f"{actor.replace('_', '.')}@test.example" for actor in ACTORS}
        grants = {
            "platform_admin": (platform.id, SystemRole.platform_admin),
            "admin_a": (op_a.id, SystemRole.operator_admin),
            "staff_a": (op_a.id, SystemRole.operator_staff),
            "admin_b": (op_b.id, SystemRole.operator_admin),
        }
        user_ids: dict[str, uuid.UUID] = {}
        for actor in ACTORS:
            user = create_user(db, email=emails[actor], password=PASSWORD)
            user_ids[actor] = user.id
            if actor in grants:
                tenant_id, role_name = grants[actor]
                role = get_system_role(db, role_name)
                db.add(Membership(user_id=user.id, tenant_id=tenant_id, role_id=role.id))

        # Operator A has verified PestPac access; operator B has none set up.
        db.add(
            PestPacConnection(
                operator_id=op_a.id,
                base_url=PESTPAC_BASE,
                client_id="client-a",
                username="api-user-a",
                client_secret_enc=encrypt("secret-a"),
                password_enc=encrypt("password-a"),
                api_key_enc=encrypt("apikey-a-1234"),
                api_key_last4="1234",
                status=ConnectionStatus.verified,
                pestpac_company_id=1,
                pestpac_company_name="Select Exterminating",
            )
        )
        company_a = Company(operator_id=op_a.id, name="Acme Restaurants")
        company_b = Company(operator_id=op_b.id, name="Beta Hotels")
        db.add_all([company_a, company_b])
        db.flush()
        bill_to_a = BillTo(
            operator_id=op_a.id,
            company_id=company_a.id,
            pestpac_bill_to_id=175101,
            name="Acme HQ",
            description="Company-level billing",
        )
        db.add(bill_to_a)
        db.flush()
        location_a = Location(
            operator_id=op_a.id,
            bill_to_id=bill_to_a.id,
            pestpac_location_id=800001,
            pestpac_company="ACME TACOS - STORE #1",
            pestpac_active=True,
            pestpac_fetched_at=datetime.now(UTC),
        )
        db.add(location_a)
        db.flush()
        sync_job_a = SyncJob(
            operator_id=op_a.id,
            kind=SyncJobKind.bill_to_service_orders,
            status=SyncJobStatus.succeeded,
            bill_to_id=bill_to_a.id,
            progress={},
            attempts=1,
        )
        db.add(sync_job_a)
        service_order_a = ServiceOrder(
            operator_id=op_a.id,
            bill_to_id=bill_to_a.id,
            location_id=location_a.id,
            pestpac_order_id=700001,
            pestpac_location_id=800001,
            posted=False,
            pestpac_fetched_at=datetime.now(UTC),
        )
        db.add(service_order_a)
        db.commit()
        return World(
            platform_id=platform.id,
            op_a=op_a.id,
            op_b=op_b.id,
            company_a=company_a.id,
            bill_to_a=bill_to_a.id,
            company_b=company_b.id,
            emails=emails,
            user_ids=user_ids,
            location_a=location_a.id,
            sync_job_a=sync_job_a.id,
            service_order_a=service_order_a.id,
        )


ONBOARDED_BILL_TO = 180020


@pytest.fixture
def onboarded(client, world, pestpac):
    """Bill-to 180020 under company A, with its three fixture locations synced."""
    admin = headers_for(client, world.emails["admin_a"])
    resp = client.post(
        f"/v1/companies/{world.company_a}/bill-tos",
        json={"pestpac_bill_to_id": ONBOARDED_BILL_TO},
        headers=admin,
    )
    assert resp.status_code == 201
    return {"headers": admin, "bill_to_id": resp.json()["id"]}
