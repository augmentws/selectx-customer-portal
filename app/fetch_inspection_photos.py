"""Fetch GoCanvas photos for inspection submissions already loaded (backfill and retries).

    python -m app.fetch_inspection_photos --operator-id UUID [--submission-id 268565507 ...]

Records photo fields for submissions parsed before photos were tracked, then fetches every
photo field not fetched yet, newest submission first. Needs the operator's verified GoCanvas
API access and S3_BUCKET. Safe to rerun: stored photos are never fetched again, and failures
are retried. GoCanvas or storage being unreachable stops the run.
"""

import argparse
import logging
import sys
import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import InspectionSubmission, Tenant, TenantKind
from app.services import gocanvas_connection
from app.services.inspection_photos import (
    GoCanvasUnavailableError,
    PhotoFetchCounts,
    backfill_photo_values,
    fetch_submission_photos,
)
from app.storage import StorageError, get_storage

log = logging.getLogger("app.fetch_inspection_photos")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--operator-id", required=True, type=uuid.UUID)
    parser.add_argument(
        "--submission-id", type=int, action="append", help="GoCanvas submission id (repeatable)"
    )
    args = parser.parse_args(argv)

    counts = PhotoFetchCounts()
    with SessionLocal() as db:
        operator = db.get(Tenant, args.operator_id)
        if operator is None or operator.kind is not TenantKind.operator:
            log.error("No operator %s", args.operator_id)
            return 1
        try:
            client = gocanvas_connection.get_gocanvas_client(db, operator)
            storage = get_storage()
        except (gocanvas_connection.ConnectionNotReadyError, StorageError) as exc:
            log.error("Can't fetch photos: %s", exc)
            return 1

        query = select(InspectionSubmission).where(InspectionSubmission.operator_id == operator.id)
        if args.submission_id:
            query = query.where(InspectionSubmission.gocanvas_submission_id.in_(args.submission_id))
        submissions = db.scalars(
            query.order_by(InspectionSubmission.gocanvas_created_at.desc().nulls_last())
        ).all()
        for submission in submissions:
            backfill_photo_values(db, submission)
        db.commit()

        for submission in submissions:
            try:
                fetch_submission_photos(db, client, storage, submission, counts)
            except (GoCanvasUnavailableError, StorageError) as exc:
                db.rollback()
                log.error("Stopped at submission %s: %s", submission.gocanvas_submission_id, exc)
                log.info("Photos: %s", counts)
                return 1

    log.info("%d submissions. Photos: %s", len(submissions), counts)
    return 1 if counts.values_failed else 0


if __name__ == "__main__":
    sys.exit(main())
