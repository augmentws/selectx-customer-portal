"""Create the first administrator from BOOTSTRAP_ADMIN_* settings. Safe to run repeatedly."""

import logging
import sys

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.auth import create_user, get_user_by_email

log = logging.getLogger("app.bootstrap")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    if not settings.bootstrap_admin_email or not settings.bootstrap_admin_password:
        log.error("BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must be set")
        return 1
    with SessionLocal() as db:
        if get_user_by_email(db, settings.bootstrap_admin_email):
            log.info("Admin %s already exists; nothing to do", settings.bootstrap_admin_email)
            return 0
        create_user(
            db,
            email=settings.bootstrap_admin_email,
            password=settings.bootstrap_admin_password,
            is_admin=True,
        )
        log.info("Created admin %s", settings.bootstrap_admin_email)
    return 0


if __name__ == "__main__":
    sys.exit(main())
