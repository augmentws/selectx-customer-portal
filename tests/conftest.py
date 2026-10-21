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

import uuid  # noqa: E402

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import BillTo, Company, Membership, Tenant, TenantKind  # noqa: E402
from app.security.permissions import SystemRole  # noqa: E402
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
            text("TRUNCATE bill_tos, companies, memberships, auth_sessions, credentials, users")
        )
        conn.execute(text("DELETE FROM roles WHERE tenant_id IS NOT NULL"))
        conn.execute(text("DELETE FROM tenants WHERE kind <> 'platform'"))


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
            parent_id=platform.id, kind=TenantKind.operator, name="Operator B", slug="op-b"
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
        )
