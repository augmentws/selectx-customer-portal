"""Load every downloaded GoCanvas submission and check the parsed data holds together.

Opt-in, never in CI (the submissions are customer data and aren't committed):

    GOCANVAS_CORPUS_DIR=scripts/chiptole \
    GOCANVAS_CORPUS_FORM=docs/risk-submissions/chipotle-risk-form.json \
        pipenv run pytest tests/test_inspections_corpus.py -s
"""

import json
import os
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.load_inspections import submission_files
from app.models import InspectionKind, InspectionResponse, InspectionSubmission
from app.services.inspections import import_form, store_submission

CORPUS_DIR = os.environ.get("GOCANVAS_CORPUS_DIR")
CORPUS_FORM = os.environ.get("GOCANVAS_CORPUS_FORM")

pytestmark = pytest.mark.skipif(
    not (CORPUS_DIR and CORPUS_FORM),
    reason="set GOCANVAS_CORPUS_DIR and GOCANVAS_CORPUS_FORM to run",
)


def test_corpus_loads_completely_and_consistently(world):
    files = submission_files([Path(CORPUS_DIR)])
    payloads = [json.loads(f.read_text()) for f in files]
    form_definition = json.loads(Path(CORPUS_FORM).read_text())
    warnings: Counter[tuple[str | None, str]] = Counter()

    with SessionLocal() as db:
        form = import_form(db, world.op_a, form_definition, InspectionKind.risk)
        db.commit()
        for payload in payloads:
            result = store_submission(db, world.op_a, payload)
            db.commit()
            assert result.outcome == "created", payload["id"]
            for warning in result.submission.parse_warnings:
                warnings[(warning["field_key"], warning["issue"])] += 1

        submissions = db.scalars(select(InspectionSubmission)).all()
        assert len(submissions) == len(payloads)
        expected_responses = sum(len(p["responses"]) for p in payloads)
        assert db.scalar(select(func.count(InspectionResponse.id))) == expected_responses

        source = {p["id"]: p for p in payloads}
        for stored in submissions:
            payload = source[stored.gocanvas_submission_id]
            assert stored.unmapped_entry_ids == [], stored.gocanvas_submission_id
            assert len(stored.risk_zones) == len(form.zones)
            # Lossless: every response comes back exactly as GoCanvas sent it.
            assert [
                (r.entry_id, r.value if r.value is not None else r.value_json)
                for r in stored.responses
            ] == [(r["entry_id"], r["value"]) for r in payload["responses"]]
            for zone in stored.risk_zones:
                if zone.inspected == "n/a":
                    assert (zone.sanitation_risk, zone.structural_risk, zone.overall_risk) == (
                        None,
                        None,
                        None,
                    )

        # Reloading changes nothing.
        assert {store_submission(db, world.op_a, p).outcome for p in payloads} == {"unchanged"}

    print(f"\n{len(payloads)} submissions, {expected_responses} responses")
    print("Parse warnings (field, issue: count):")
    for (field_key, issue), count in warnings.most_common():
        print(f"  {field_key}, {issue}: {count}")
