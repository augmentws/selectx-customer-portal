from sqlalchemy import func, select

from app import bootstrap
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Membership, User
from app.services.rbac import get_platform_tenant


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
        users = db.scalars(select(User).where(User.email == "boot@test.example")).all()
        assert len(users) == 1
        platform = get_platform_tenant(db)
        memberships = db.scalars(select(Membership).where(Membership.user_id == users[0].id)).all()
        assert [(m.tenant_id, m.role.name) for m in memberships] == [
            (platform.id, "platform_admin")
        ]
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_bootstrap_grants_membership_to_existing_user(monkeypatch, world):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", world.emails["no_role"])
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "unused-because-user-exists")
    get_settings.cache_clear()
    try:
        assert bootstrap.main() == 0
    finally:
        get_settings.cache_clear()
    with SessionLocal() as db:
        roles = db.scalars(
            select(Membership).where(Membership.user_id == world.user_ids["no_role"])
        ).all()
        assert [m.role.name for m in roles] == ["platform_admin"]
