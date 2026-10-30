"""Extract findings for a company's worked orders that have no report (backfill).

    python -m app.extract_findings --company-id UUID [--enable | --disable] [--dry-run]
        [--limit N] [--retry-failed] [--run]

Queues the company's worked orders that have a technician comment or SERVICE notes to read and
no current findings, newest first (--limit caps how many). The worker extracts them; --run does
it here instead, then exits (it runs every ready request, any company's). --retry-failed requeues
the company's failed requests. --enable/--disable sets whether the company's orders are queued
automatically when they're posted. --dry-run reports what would be queued without saving.

This sends the orders' notes and technician comments to OpenRouter.
"""

import argparse
import logging
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app import worker
from app.db.session import SessionLocal
from app.models import Company, InspectionFinding
from app.services import findings_extraction

log = logging.getLogger("app.extract_findings")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--company-id", required=True, type=uuid.UUID)
    switch = parser.add_mutually_exclusive_group()
    switch.add_argument("--enable", action="store_true", help="queue orders when they're posted")
    switch.add_argument("--disable", action="store_true", help="stop queueing them")
    parser.add_argument("--dry-run", action="store_true", help="report, don't save")
    parser.add_argument("--limit", type=int, help="queue at most this many orders")
    parser.add_argument("--retry-failed", action="store_true", help="requeue failed requests")
    parser.add_argument("--run", action="store_true", help="extract now instead of the worker")
    args = parser.parse_args(argv)
    if args.dry_run and args.run:
        parser.error("--dry-run and --run don't go together")

    with SessionLocal() as db:
        company = db.get(Company, args.company_id)
        if company is None:
            log.error("No company %s", args.company_id)
            return 1
        if args.enable or args.disable:
            company.extract_findings = args.enable
        requeued = findings_extraction.requeue_failed(db, company.id) if args.retry_failed else 0
        plan = findings_extraction.backfill(db, company, limit=args.limit, dry_run=args.dry_run)
        enabled = company.extract_findings
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        log.info("%s%s", company.name, " (dry run)" if args.dry_run else "")
        log.info("Extract when posted: %s", "on" if enabled else "off")
        log.info("Worked orders: %d; with something to read: %d", plan.worked, plan.readable)
        log.info("Already have findings: %d; already queued or failed: %d", plan.done, plan.waiting)
        if args.retry_failed:
            log.info("%s: %d", "Failed, would requeue" if args.dry_run else "Requeued", requeued)
        log.info("%s: %d", "Would queue" if args.dry_run else "Queued", plan.queued)

    if not args.run:
        return 0
    started = datetime.now(UTC)
    worker._Stop.requested = False
    ran = worker.run_pending_findings()
    with SessionLocal() as db:
        extracted, cost = db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(InspectionFinding.usage["cost"].as_float()), 0),
            ).where(
                InspectionFinding.source == "extraction",
                InspectionFinding.extracted_at >= started,
            )
        ).one()
    log.info("Ran %d requests: %d extracted, cost $%.4f", ran, extracted, cost)
    return 0


if __name__ == "__main__":
    sys.exit(main())
