"""Reconcile RBAC with the code registry and ensure the first platform admin exists.

Uses BOOTSTRAP_ADMIN_* settings. Safe to run repeatedly: `python -m app.bootstrap`.
"""

import logging
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Membership
from app.security.permissions import SystemRole
from app.services.auth import create_user, get_user_by_email
from app.services.members import get_membership
from app.services.rbac import get_platform_tenant, get_system_role, sync_rbac

log = logging.getLogger("app.bootstrap")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        log.error("BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must be set")
        return 1
    with SessionLocal() as db:
        for change in sync_rbac(db):
            log.info("RBAC: %s", change)

        platform = get_platform_tenant(db)
        role = get_system_role(db, SystemRole.platform_admin)
        if role is None:
            raise RuntimeError("platform_admin role missing after sync")

        user = get_user_by_email(db, settings.bootstrap_admin_email)
        if user is None:
            user = create_user(
                db,
                email=settings.bootstrap_admin_email,
                password=settings.bootstrap_admin_password,
            )
            log.info("Created admin %s", settings.bootstrap_admin_email)

        if get_membership(db, platform, user.id) is None:
            db.add(Membership(user_id=user.id, tenant_id=platform.id, role_id=role.id))
            log.info("Granted platform_admin to %s", user.email)
        else:
            log.info("Admin %s already set up; nothing to do", user.email)
        db.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
