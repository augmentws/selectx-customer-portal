"""Background worker: runs queued service-order sync jobs.

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
from app.services import sync_jobs

log = logging.getLogger("app.worker")


class _Stop:
    requested = False


def run_pending() -> int:
    """Run every claimable job; returns how many ran."""
    ran = 0
    while not _Stop.requested:
        with SessionLocal() as db:
            job = sync_jobs.claim_next(db)
            if job is None:
                return ran
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="run queued jobs, then exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    validate_keys()

    def stop(signum, _frame):
        log.info("Signal %s received; finishing the current job", signum)
        _Stop.requested = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    if args.once:
        run_pending()
        return 0
    poll = get_settings().worker_poll_seconds
    log.info("Worker started; polling every %ss", poll)
    while not _Stop.requested:
        if run_pending() == 0:
            time.sleep(poll)
    return 0


if __name__ == "__main__":
    sys.exit(main())
