import os

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

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from alembic import command  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.auth import create_user  # noqa: E402

ADMIN_EMAIL = "admin@test.example"
USER_EMAIL = "user@test.example"
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
    with engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def users():
    with SessionLocal() as db:
        create_user(db, email=ADMIN_EMAIL, password=PASSWORD, is_admin=True)
        create_user(db, email=USER_EMAIL, password=PASSWORD)


def login(client: TestClient, email: str = USER_EMAIL, password: str = PASSWORD):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


@pytest.fixture
def auth_headers(client, users) -> dict[str, str]:
    token = login(client).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
