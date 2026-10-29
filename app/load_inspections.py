"""Load GoCanvas inspection submissions from JSON files (GET /submissions/{id} bodies).

    python -m app.load_inspections --operator-id UUID \
        --form docs/risk-submissions/chipotle-risk-form.json --kind risk scripts/chiptole

Imports the form definition first (re-importing replaces its field map), then each submission
file; directories are read for `<digits>.json` files. Each submission commits on its own and
reloading is safe: unchanged submissions are skipped (--reparse re-parses them after the
parsing rules change). Ends with a summary of parse warnings.

Each submission's photos are then fetched from GoCanvas into object storage (needs the
operator's verified GoCanvas API access and S3_BUCKET; --no-photos skips them, and
`python -m app.fetch_inspection_photos` fetches them later). Photos that failed are retried on
the next run.
"""

import argparse
import json
import logging
import re
import sys
import uuid
from collections import Counter
from pathlib import Path

from app.db.session import SessionLocal
from app.models import InspectionKind, Tenant, TenantKind
from app.services import gocanvas_connection
from app.services.inspection_photos import (
    GoCanvasUnavailableError,
    PhotoFetchCounts,
    fetch_submission_photos,
)
from app.services.inspections import InspectionError, import_form, store_submission
from app.storage import StorageError, get_storage

log = logging.getLogger("app.load_inspections")
SUBMISSION_FILE = re.compile(r"^\d+\.json$")


def submission_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.iterdir() if SUBMISSION_FILE.match(p.name)))
        else:
            files.append(path)
    return files


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+", type=Path, help="submission files or directories")
    parser.add_argument("--operator-id", required=True, type=uuid.UUID)
    parser.add_argument("--form", required=True, type=Path, help="GoCanvas form definition")
    parser.add_argument("--kind", required=True, choices=[k.value for k in InspectionKind])
    parser.add_argument(
        "--reparse", action="store_true", help="re-parse unchanged submissions (rules changed)"
    )
    parser.add_argument("--no-photos", action="store_true", help="don't fetch photos")
    args = parser.parse_args(argv)

    outcomes: Counter[str] = Counter()
    issues: Counter[tuple[str | None, str]] = Counter()
    with SessionLocal() as db:
        operator = db.get(Tenant, args.operator_id)
        if operator is None or operator.kind is not TenantKind.operator:
            log.error("No operator %s", args.operator_id)
            return 1
        photos = None
        if not args.no_photos:
            try:
                photos = (gocanvas_connection.get_gocanvas_client(db, operator), get_storage())
            except (gocanvas_connection.ConnectionNotReadyError, StorageError) as exc:
                log.error("Can't fetch photos: %s. Use --no-photos to load without them.", exc)
                return 1
        photo_counts = PhotoFetchCounts()
        form = import_form(
            db, operator.id, json.loads(args.form.read_text()), InspectionKind(args.kind)
        )
        db.commit()
        log.info(
            "Form %s (v%s): %d zones, %d fields",
            form.name,
            form.version,
            len(form.zones),
            len(form.fields),
        )

        for path in submission_files(args.paths):
            try:
                result = store_submission(
                    db, operator.id, json.loads(path.read_text()), reparse=args.reparse
                )
                db.commit()
            except (InspectionError, json.JSONDecodeError) as exc:
                db.rollback()
                log.error("%s: %s", path.name, exc)
                outcomes["failed"] += 1
                continue
            outcomes[result.outcome] += 1
            if result.outcome in ("created", "updated"):
                for warning in result.submission.parse_warnings:
                    issues[(warning["field_key"], warning["issue"])] += 1
            if photos is not None:
                try:
                    fetch_submission_photos(db, *photos, result.submission, photo_counts)
                except (GoCanvasUnavailableError, StorageError) as exc:
                    db.rollback()
                    log.error("Stopped fetching photos: %s", exc)
                    outcomes["photo fetch stopped"] += 1
                    photos = None

    log.info("Submissions: %s", ", ".join(f"{n} {k}" for k, n in sorted(outcomes.items())))
    if not args.no_photos:
        log.info("Photos: %s", photo_counts)
    if issues:
        log.info("Parse warnings (field, issue: count):")
        for (field_key, issue), count in issues.most_common():
            log.info("  %s, %s: %d", field_key, issue, count)
    failed = outcomes["failed"] or outcomes["photo fetch stopped"] or photo_counts.values_failed
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
