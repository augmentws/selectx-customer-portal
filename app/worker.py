"""Background worker: handles webhooks, runs sync jobs, report drafts, and findings extraction,
clears webhook bodies.

    python -m app.worker            # run until stopped (Ctrl-C / SIGTERM)
    python -m app.worker --once     # run queued jobs, then exit

Safe to run several at once: jobs are claimed with FOR UPDATE SKIP LOCKED.
"""

import argparse
import logging
import signal
import sys
import time

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.security.secrets import validate_keys
from app.services import (
    findings_extraction,
    gocanvas,
    service_reports,
    sync_jobs,
    webhook_handlers,
    webhooks,
)

log = logging.getLogger("app.worker")


class _Stop:
    requested = False


def run_pending() -> int:
    """Handle webhook events, then run every claimable job, draft, and findings extraction;
    returns how many ran. With SYNC_ACTIVE off, only the LLM work: events and jobs wait, since
    both call PestPac."""
    if not get_settings().sync_active:
        return run_pending_drafts() + run_pending_findings()
    return (
        run_pending_webhooks() + run_pending_jobs() + run_pending_drafts() + run_pending_findings()
    )


def run_pending_webhooks() -> int:
    """Process stored webhook events that have a handler (they may queue sync jobs)."""
    ran = 0
    while not _Stop.requested:
        with SessionLocal() as db:
            event = webhook_handlers.claim_next(db)
            if event is None:
                return ran
            event_id = event.id
            try:
                webhook_handlers.process(db, event)
                db.commit()
            except Exception as exc:
                # A bug, not a missing record (those are recorded by process). Mark the event
                # failed so it isn't retried in a loop.
                log.exception("Webhook event %s crashed", event_id)
                db.rollback()
                webhook_handlers.mark_crashed(db, event_id, f"Handler error: {type(exc).__name__}")
            ran += 1
    return ran


def run_pending_jobs() -> int:
    """Run every claimable sync job; returns how many ran."""
    ran = 0
    while not _Stop.requested:
        with SessionLocal() as db:
            job = sync_jobs.claim_next(db)
            if job is None:
                break
            log.info("Running %s job %s (attempt %s)", job.kind, job.id, job.attempts)
            job_id = job.id
            try:
                job = sync_jobs.run_job(db, job)
            except Exception:
                # Unexpected bug, not a PestPac failure (those are handled per location). The job
                # stays 'running'; after the stale timeout it's retried, up to the attempt limit.
                log.exception("Job %s crashed; it will be retried after the stale timeout", job_id)
                db.rollback()
                ran += 1
                continue
            log.info("Job %s finished: %s %s", job.id, job.status, job.progress.get("orders"))
            ran += 1
    return ran


def run_pending_drafts() -> int:
    """Draft every report waiting for its narrative (LLM); returns how many ran."""
    ran = 0
    while not _Stop.requested:
        with SessionLocal() as db:
            report = service_reports.claim_next_draft(db)
            if report is None:
                return ran
            report_id = report.id
            log.info("Drafting report %s", report_id)
            try:
                report = service_reports.run_draft(db, report)
            except Exception:
                # A bug, not an LLM failure (those are recorded by run_draft). Put the report
                # back to draft with a note, so it isn't retried in a loop.
                log.exception("Draft of report %s crashed", report_id)
                db.rollback()
                service_reports.mark_draft_crashed(db, report_id)
                ran += 1
                continue
            log.info("Report %s drafted: %s", report.id, report.draft_error or "ok")
            ran += 1
    return ran


def run_pending_findings() -> int:
    """Extract findings for every ready request (LLM); returns how many ran."""
    ran = 0
    while not _Stop.requested:
        with SessionLocal() as db:
            req = findings_extraction.claim_next(db)
            if req is None:
                return ran
            order_id = req.service_order_id
            try:
                outcome = findings_extraction.run(db, req)
            except Exception:
                # A bug, not an LLM failure (those are recorded by run). Take the request out of
                # the queue with a note, so it isn't retried in a loop.
                log.exception("Findings for order %s crashed", order_id)
                db.rollback()
                findings_extraction.mark_crashed(db, order_id)
                ran += 1
                continue
            log.info("Findings for order %s: %s", order_id, outcome)
            ran += 1
    return ran


PURGE_INTERVAL_SECONDS = 3600


def purge_webhook_bodies() -> None:
    with SessionLocal() as db:
        cleared = webhooks.purge_raw_bodies(db) + gocanvas.purge_raw_bodies(db)
    if cleared:
        log.info("Cleared %s expired webhook bodies", cleared)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="run queued jobs, then exit")
    parser.add_argument(
        "--requeue-failed-invoices",
        action="store_true",
        help="first send failed invoice events whose invoice isn't stored back to the queue",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    validate_keys()

    def stop(signum, _frame):
        log.info("Signal %s received; finishing the current job", signum)
        _Stop.requested = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    if args.requeue_failed_invoices:
        with SessionLocal() as db:
            log.info("Requeued %s invoice events", webhook_handlers.requeue_failed_invoices(db))

    if args.once:
        run_pending()
        purge_webhook_bodies()
        return 0
    if not get_settings().sync_active:
        log.warning("SYNC_ACTIVE is off: webhook events and sync jobs wait; nothing calls PestPac")
    poll = get_settings().worker_poll_seconds
    log.info("Worker started; polling every %ss", poll)
    last_purge = float("-inf")
    while not _Stop.requested:
        if time.monotonic() - last_purge >= PURGE_INTERVAL_SECONDS:
            purge_webhook_bodies()
            last_purge = time.monotonic()
        if run_pending() == 0:
            time.sleep(poll)
    return 0


if __name__ == "__main__":
    sys.exit(main())
