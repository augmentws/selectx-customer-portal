from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update

from app import extract_findings, worker
from app.db.session import SessionLocal
from app.integrations.openrouter import Usage
from app.models import (
    Company,
    InspectionFinding,
    InspectionFindingRequest,
    Note,
    ServiceOrder,
)
from app.services import findings_extraction, inspection_findings, llm_tasks
from tests.conftest import ONBOARDED_BILL_TO, pestpac_invoice, pestpac_order
from tests.test_invoices import ORDER_ID, STORE, _drain_with_order_sync, _invoice_webhook, _order
from tests.test_service_orders import _sync
from tests.test_service_reports import DRAFT, _findings

FINDINGS = DRAFT["findings"]


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def run_task(task, data, **kwargs):
        calls.append((task, data, kwargs))
        return llm_tasks.TaskResult(
            output=task.output.model_validate(FINDINGS),
            model="test/model",
            usage=Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150, cost=0.002),
            attempts=1,
        )

    monkeypatch.setattr(llm_tasks, "run_task", run_task)
    return calls


@pytest.fixture
def no_llm(monkeypatch):
    def run_task(task, data, **_):
        raise AssertionError("the LLM must not be called")

    monkeypatch.setattr(llm_tasks, "run_task", run_task)


def _run():
    worker._Stop.requested = False
    return worker.run_pending_findings()


def _worked(world, comment=None):
    with SessionLocal() as db:
        db.execute(
            update(ServiceOrder)
            .where(ServiceOrder.id == world.service_order_a)
            .values(posted=True, technician_comment=comment)
        )
        db.commit()


def _notes(world, *notes):
    """(pestpac id, date, code, text, linked to the order)"""
    with SessionLocal() as db:
        db.add_all(
            Note(
                operator_id=world.op_a,
                pestpac_note_id=n,
                note_date=date,
                note_code=code,
                note=text,
                created_by_user="PTECH",
                location_id=world.location_a,
                service_order_id=world.service_order_a if linked else None,
                pestpac_fetched_at=datetime.now(UTC),
            )
            for n, date, code, text, linked in notes
        )
        db.commit()


def _request(world, *, wait=False):
    with SessionLocal() as db:
        findings_extraction.request(db, world.op_a, [world.service_order_a], wait=wait)
        db.commit()


def _requests():
    with SessionLocal() as db:
        return [
            (r.service_order_id, r.requested_at is not None, r.attempts, r.error)
            for r in db.scalars(select(InspectionFindingRequest))
        ]


def _enable(world, on=True):
    with SessionLocal() as db:
        db.execute(update(Company).where(Company.id == world.company_a).values(extract_findings=on))
        db.commit()


def test_extracts_from_the_comment_and_the_visits_service_notes(world, fake_llm):
    _worked(world, comment="  No activity. Gap at the trash room wall.  ")
    _notes(
        world,
        (1, datetime(2026, 10, 5, 10, 15), "SERVICE", "Inspected the serving line.", False),
        (2, datetime(2026, 9, 20, 9, 0), "SERVICE", "Linked, weeks earlier.", True),
        (3, datetime(2026, 10, 5, 11, 0), "BILLING", "Bill $185.", False),
        (4, datetime(2026, 10, 5, 11, 0), "ALERT", "Store closes at 10pm", False),
        (5, datetime(2026, 10, 4, 16, 0), "SERVICE", "Day before.", False),
        (6, datetime(2026, 10, 5, 12, 0), "SERVICE", "   ", False),
    )
    _request(world)
    assert _run() == 1

    [(task, data, kwargs)] = fake_llm
    assert task.name == "inspection_findings"
    assert inspection_findings.RULES in task.instructions
    assert kwargs == {"model": None}  # FINDINGS_LLM_MODEL unset: the default model
    assert [n["text"] for n in data["notes"]] == [
        "Linked, weeks earlier.",
        "Inspected the serving line.",
    ]
    assert data["technician_comment"]["text"] == "No activity. Gap at the trash room wall."
    assert data["service_order"]["work_date"] == "2026-10-05T09:30:00"
    assert data["location"]["name"]

    [row] = _findings(world)
    assert row[:6] == (
        world.service_order_a,
        "extraction",
        "qc_inspection",
        "none",
        6,
        "test/model",
    )
    with SessionLocal() as db:
        finding = db.scalar(select(InspectionFinding))
        assert finding.report_id is None
        assert finding.method_version == inspection_findings.METHOD_VERSION
    assert _requests() == []


def test_an_order_with_nothing_to_read_is_skipped(world, no_llm):
    _worked(world, comment="   ")
    _notes(world, (1, datetime(2026, 10, 5, 11, 0), "BILLING", "Bill $185.", False))
    _request(world)
    assert _run() == 1
    assert _findings(world) == []
    assert _requests() == []


def test_findings_from_a_report_draft_are_never_replaced(world, no_llm):
    _worked(world, comment="No activity.")
    with SessionLocal() as db:
        inspection_findings.save(
            db,
            operator_id=world.op_a,
            service_order_id=world.service_order_a,
            location_id=world.location_a,
            report_id=None,
            source="report_draft",
            findings=inspection_findings.FindingsOut.model_validate(FINDINGS),
            model="draft/model",
            usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2, cost=0.0),
        )
        db.commit()
    _request(world)
    assert _run() == 1
    assert _findings(world)[0][1:2] == ("report_draft",)
    assert _requests() == []


def test_a_failure_is_recorded_and_can_be_requeued(world, monkeypatch, fake_llm):
    _worked(world, comment="No activity.")

    def fails(task, data, **_):
        raise llm_tasks.LLMTaskError("The reply never validated")

    with monkeypatch.context() as m:
        m.setattr(llm_tasks, "run_task", fails)
        _request(world)
        assert _run() == 1
        assert _run() == 0  # out of the queue: not retried in a loop
    assert _findings(world) == []
    assert _requests() == [(world.service_order_a, False, 1, "The reply never validated")]

    with SessionLocal() as db:
        assert findings_extraction.requeue_failed(db, world.company_a) == 1
        db.commit()
    assert _run() == 1
    assert _findings(world)[0][1] == "extraction"
    assert _requests() == []


def test_a_request_waits_for_the_notes_to_sync(world, fake_llm):
    _worked(world, comment="No activity.")
    _request(world, wait=True)
    assert _run() == 0
    assert _requests() == [(world.service_order_a, True, 0, None)]


def test_posting_queues_only_for_companies_that_extract(client, world, onboarded, pestpac, no_llm):
    pestpac.orders_by_location[STORE] = [pestpac_order(1, STORE, ONBOARDED_BILL_TO, Posted=False)]
    _sync(client, onboarded)
    pestpac.orders_by_location[STORE] = [pestpac_order(1, STORE, ONBOARDED_BILL_TO, Posted=True)]
    _sync(client, onboarded)
    assert _requests() == []  # off by default

    _enable(world)
    pestpac.orders_by_location[STORE] = [pestpac_order(2, STORE, ONBOARDED_BILL_TO, Posted=False)]
    _sync(client, onboarded)
    assert _requests() == []  # not worked yet
    pestpac.orders_by_location[STORE] = [pestpac_order(2, STORE, ONBOARDED_BILL_TO, Posted=True)]
    _sync(client, onboarded)
    with SessionLocal() as db:
        order_2 = db.scalar(select(ServiceOrder.id).where(ServiceOrder.pestpac_order_id == 2))
    assert _requests() == [(order_2, True, 0, None)]  # waiting REQUEST_DELAY, so not run yet

    _sync(client, onboarded)  # still posted: not queued again
    assert len(_requests()) == 1


def test_an_order_posted_by_its_invoice_is_queued(client, world, onboarded, pestpac, no_llm):
    _enable(world)
    # We saw the order open and never saw it posted; then it was billed.
    pestpac.orders_by_location[STORE] = [pestpac_order(ORDER_ID, STORE, ONBOARDED_BILL_TO)]
    pestpac.invoices[3494466] = pestpac_invoice()
    _drain_with_order_sync(client, onboarded)
    assert _requests() == []
    _invoice_webhook(client)
    worker._Stop.requested = False
    worker.run_pending()
    assert _requests() == [(_order().id, True, 0, None)]


def test_backfill_command(world, fake_llm, caplog):
    _worked(world, comment="No activity.")
    caplog.set_level("INFO", logger="app.extract_findings")
    company = ["--company-id", str(world.company_a)]

    assert extract_findings.main([*company, "--dry-run", "--enable"]) == 0
    assert "Would queue: 1" in caplog.text
    assert _requests() == []
    with SessionLocal() as db:
        assert db.get(Company, world.company_a).extract_findings is False  # dry run

    caplog.clear()
    assert extract_findings.main([*company, "--enable", "--run"]) == 0
    assert "Queued: 1" in caplog.text
    assert "Ran 1 requests: 1 extracted, cost $0.0020" in caplog.text
    assert _findings(world)[0][1] == "extraction"
    with SessionLocal() as db:
        assert db.get(Company, world.company_a).extract_findings is True

    caplog.clear()
    assert extract_findings.main(company) == 0  # current findings: nothing to queue
    assert "Already have findings: 1" in caplog.text
    assert "Queued: 0" in caplog.text
