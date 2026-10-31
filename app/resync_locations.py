"""Queue "Sync location" (areas, documents, conditions, files) for every location we hold.

    python -m app.resync_locations [--operator-id UUID] [--company-id UUID] [--bill-to-id UUID]
        [--dry-run] [--run]

Queues one location sync per active bill-to (narrowed by the options), skipping bill-tos that
already have one queued or running. The worker runs them; --run runs every queued sync job here
instead, then exits. Needs SYNC_ACTIVE on, since every job calls PestPac. Use it after adding
something "Sync location" stores, so history is filled for every location.
"""

import argparse
import logging
import sys
import uuid

from sqlalchemy import func, select

from app import worker
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import BillTo, Company, Location
from app.services import sync_jobs

log = logging.getLogger("app.resync_locations")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--operator-id", type=uuid.UUID)
    parser.add_argument("--company-id", type=uuid.UUID)
    parser.add_argument("--bill-to-id", type=uuid.UUID)
    parser.add_argument("--dry-run", action="store_true", help="report, don't queue")
    parser.add_argument("--run", action="store_true", help="run the jobs here, not the worker")
    args = parser.parse_args(argv)
    if args.dry_run and args.run:
        parser.error("--dry-run and --run don't go together")
    if not args.dry_run and not get_settings().sync_active:
        log.error("SYNC_ACTIVE is off: location syncs would wait, since they call PestPac")
        return 1

    with SessionLocal() as db:
        query = (
            select(BillTo)
            .join(Company, Company.id == BillTo.company_id)
            .where(BillTo.is_active.is_(True), Company.is_active.is_(True))
            .order_by(BillTo.operator_id, BillTo.company_id, BillTo.pestpac_bill_to_id)
        )
        if args.operator_id:
            query = query.where(BillTo.operator_id == args.operator_id)
        if args.company_id:
            query = query.where(BillTo.company_id == args.company_id)
        if args.bill_to_id:
            query = query.where(BillTo.id == args.bill_to_id)
        bill_tos = list(db.scalars(query))
        locations = 0
        for bill_to in bill_tos:
            count = db.scalar(
                select(func.count()).where(
                    Location.bill_to_id == bill_to.id, Location.removed_at.is_(None)
                )
            )
            locations += count
            if args.dry_run:
                log.info("%s: %d locations", bill_to.name, count)
                continue
            # Returns the bill-to's waiting job instead when one is queued or running.
            job = sync_jobs.enqueue_bill_to_location_sync(db, bill_to, requested_by=None)
            log.info("%s: %d locations, job %s (%s)", bill_to.name, count, job.id, job.status.value)
        db.commit()

    log.info("%d bill-tos, %d locations%s", len(bill_tos), locations, " (dry run)" * args.dry_run)
    if args.run:
        worker._Stop.requested = False
        log.info("Ran %d sync jobs", worker.run_pending_jobs())
    return 0


if __name__ == "__main__":
    sys.exit(main())
