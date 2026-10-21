from sqlalchemy import func, select

from app import bootstrap
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import User


def test_bootstrap_is_idempotent(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "boot@test.example")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "bootstrap-password")
    get_settings.cache_clear()
    try:
        assert bootstrap.main() == 0
        assert bootstrap.main() == 0
    finally:
        get_settings.cache_clear()

    with SessionLocal() as db:
        admins = db.scalars(select(User).where(User.email == "boot@test.example")).all()
        assert len(admins) == 1
        assert admins[0].is_admin
        assert db.scalar(select(func.count()).select_from(User)) == 1
