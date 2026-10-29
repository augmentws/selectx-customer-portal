"""Import contacts and store names from Chipotle's Restaurant Leader Report (CSV export).

    python -m app.import_leader_report --operator-id UUID --company-id UUID \
        Restaurant_Leader_Report.csv

Only OPEN stores whose number matches one of the company's locations ("... #2301") are imported;
PROJECT stores and stores we don't serve are skipped. Each match gets the store's own phone and
email, its Executive Team Director, Team Director, and Restaurant Leader as contacts, and its
`description` set to the report's store name. Links this report no longer lists are marked
removed. Re-running is safe. --dry-run reports what would change without saving.
"""

import argparse
import csv
import logging
import sys
import uuid
from pathlib import Path

from app.db.session import SessionLocal
from app.models import Company
from app.services.contacts import LeaderReportError, import_leader_report

log = logging.getLogger("app.import_leader_report")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", type=Path, help="the report as CSV")
    parser.add_argument("--operator-id", required=True, type=uuid.UUID)
    parser.add_argument("--company-id", required=True, type=uuid.UUID)
    parser.add_argument("--dry-run", action="store_true", help="report, don't save")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        company = db.get(Company, args.company_id)
        if company is None or company.operator_id != args.operator_id:
            log.error("No company %s under operator %s", args.company_id, args.operator_id)
            return 1
        company_name = company.name
        with args.path.open(newline="", encoding="utf-8-sig") as f:
            try:
                result = import_leader_report(db, company.operator_id, company.id, csv.reader(f))
            except LeaderReportError as exc:
                log.error("%s: %s", args.path.name, exc)
                return 1
        if args.dry_run:
            db.rollback()
        else:
            db.commit()

    log.info(
        "%s: %d stores (%s)", company_name, result.rows, "dry run" if args.dry_run else "saved"
    )
    log.info("Not OPEN, skipped: %s", dict(result.skipped_status) or "none")
    log.info("Matched a location: %d; not ours: %d", result.matched, len(result.unmatched))
    if result.ambiguous:
        log.info("Match several locations, skipped: %s", ", ".join(result.ambiguous))
    log.info("Descriptions changed: %d", result.descriptions_changed)
    log.info("Contacts: %s", dict(result.contacts) or "no changes")
    log.info("Links: %s", dict(result.links) or "no changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
