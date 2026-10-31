"""Findings without a report: a worked order's findings read from its notes by the LLM, for the
orders nobody drafts a report for. Same rules and storage as drafting (`inspection_findings`).

Queue: `inspection_finding_requests`, one row per order. An order is queued when it's posted, if
its company has `extract_findings` on (`request_if_enabled`), or by the backfill command
(`python -m app.extract_findings`). The worker claims requests oldest first once they're
REQUEST_DELAY old (an order sync stores the location's notes after its orders), reads the order's
technician comment and its SERVICE notes (linked to the order or on its work date), and stores the
findings with source `extraction`. Findings from a report draft are never replaced: a person chose
those notes. An order with nothing to read is skipped. A failure keeps the request, with its
error, out of the queue until it's requeued.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Date, and_, cast, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.openrouter import OpenRouterError
from app.models import (
    BillTo,
    Company,
    InspectionFinding,
    InspectionFindingRequest,
    Location,
    Note,
    ServiceOrder,
)
from app.services import inspection_findings, llm_tasks, reports

log = logging.getLogger(__name__)

# Notes that describe the visit. The others are store hours (ALERT), service-instruction
# changes (HHALERT), office notes (NOTES), call-aheads, and billing (which carries prices).
SERVICE_NOTE_CODES = ("SERVICE",)
# How long a request waits before it's run: long enough for the order sync that posted it to
# store the location's notes.
REQUEST_DELAY = timedelta(minutes=5)

INSTRUCTIONS = (
    """You read a pest-control technician's notes from one service visit by Select
Exterminating and record what they say was found and done, as data for Select's internal tracking.

INPUT
A JSON object with:
- location: the store's name and address.
- store_number: the customer's store number, when known.
- service_order: the visit (work_date, service_code, description, technician_name).
- notes: the technician's notes from the visit, oldest first (date, author, text).
- technician_comment: the technician's comment on the service order (author, text), or null.
The notes and the technician comment are the only sources; treat them together as "the notes".
Never invent anything: when the notes don't say, use null or an empty list.

OUTPUT
Reply with a JSON object with exactly these keys:
"""
    + inspection_findings.RULES
)

TASK = llm_tasks.LLMTask(
    name="inspection_findings",
    instructions=INSTRUCTIONS,
    output=inspection_findings.FindingsOut,
    # Normal replies, reasoning included, stay under ~18k tokens.
    max_tokens=24_000,
)


# --- Input ----------------------------------------------------------------------------------


def _visit_note(order_id: Any, location_id: Any, work_date: Any) -> ColumnElement[bool]:
    """A SERVICE note with text from the order's visit: linked to it, or on its work date (a
    date, or a column of dates; None when the order has none)."""
    same_visit = Note.service_order_id == order_id
    if work_date is not None:
        same_visit = or_(same_visit, cast(Note.note_date, Date) == work_date)
    return and_(
        Note.location_id == location_id,
        Note.note_code.in_(SERVICE_NOTE_CODES),
        func.length(func.trim(Note.note)) > 0,
        same_visit,
    )


def has_something_to_read() -> ColumnElement[bool]:
    """For queries over service orders: a technician comment or a visit note to read."""
    return or_(
        func.length(func.trim(ServiceOrder.technician_comment)) > 0,
        exists().where(
            _visit_note(
                ServiceOrder.id, ServiceOrder.location_id, cast(ServiceOrder.work_date, Date)
            )
        ),
    )


def extraction_input(db: Session, order: ServiceOrder) -> dict[str, Any] | None:
    """What the LLM reads, shaped like a report draft's input; None when there's nothing."""
    comment = (order.technician_comment or "").strip()
    notes: list[Note] = []
    if order.location_id is not None:
        work_date = order.work_date.date() if order.work_date else None
        notes = list(
            db.scalars(
                select(Note)
                .where(_visit_note(order.id, order.location_id, work_date))
                .order_by(Note.note_date, Note.id)
            )
        )
    if not comment and not notes:
        return None
    context = (
        reports.build_context(db, db.get(Location, order.location_id))
        if order.location_id is not None
        else None
    )
    return {
        "location": context.location.model_dump(mode="json") if context else None,
        "store_number": context.store_number if context else None,
        "service_order": {
            "work_date": order.work_date.isoformat() if order.work_date else None,
            "service_code": order.service_code,
            "description": order.description,
            "technician_name": order.technician_name,
        },
        "notes": [
            {
                "date": n.note_date.isoformat() if n.note_date else None,
                "author": n.created_by_name,
                "text": n.note,
            }
            for n in notes
        ],
        "technician_comment": (
            {"author": order.technician_name, "text": comment} if comment else None
        ),
    }


# --- Queue ----------------------------------------------------------------------------------


def request(
    db: Session, operator_id: uuid.UUID, order_ids: list[uuid.UUID], *, wait: bool = True
) -> int:
    """Queue the orders (again, if they failed). `wait=False` makes them ready at once (the
    backfill: their notes are already stored). Doesn't commit."""
    if not order_ids:
        return 0
    now = datetime.now(UTC)
    ready = now if wait else now - REQUEST_DELAY
    stmt = pg_insert(InspectionFindingRequest).values(
        [
            {
                "service_order_id": i,
                "operator_id": operator_id,
                "requested_at": ready,
                "attempts": 0,
            }
            for i in order_ids
        ]
    )
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=["service_order_id"],
            set_={"requested_at": stmt.excluded.requested_at, "error": None},
        )
    )
    return len(order_ids)


def request_if_enabled(db: Session, order: ServiceOrder, company_id: uuid.UUID) -> bool:
    """Queue a newly posted order if its company extracts findings. Doesn't commit."""
    if not db.scalar(select(Company.extract_findings).where(Company.id == company_id)):
        return False
    request(db, order.operator_id, [order.id])
    return True


def requeue_failed(db: Session, company_id: uuid.UUID) -> int:
    """Put the company's failed requests back in the queue, ready at once. Doesn't commit."""
    company_orders = (
        select(ServiceOrder.id)
        .join(BillTo, BillTo.id == ServiceOrder.bill_to_id)
        .where(BillTo.company_id == company_id)
    )
    result = db.execute(
        update(InspectionFindingRequest)
        .where(
            InspectionFindingRequest.requested_at.is_(None),
            InspectionFindingRequest.service_order_id.in_(company_orders),
        )
        .values(requested_at=datetime.now(UTC) - REQUEST_DELAY, error=None)
    )
    return result.rowcount


def claim_next(db: Session) -> InspectionFindingRequest | None:
    """Lock the oldest ready request; held until `run` commits, so a worker that dies mid-call
    releases it."""
    return db.scalar(
        select(InspectionFindingRequest)
        .where(InspectionFindingRequest.requested_at <= datetime.now(UTC) - REQUEST_DELAY)
        .order_by(InspectionFindingRequest.requested_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def run(db: Session, req: InspectionFindingRequest) -> str:
    """Extract and store one order's findings; returns what happened. An LLM problem is
    recorded on the request, never raised."""
    order = db.get(ServiceOrder, req.service_order_id)
    source = db.scalar(
        select(InspectionFinding.source).where(InspectionFinding.service_order_id == order.id)
    )
    if source == "report_draft":
        db.delete(req)
        db.commit()
        return "has report findings"
    data = extraction_input(db, order)
    if data is None:
        db.delete(req)
        db.commit()
        return "nothing to read"
    settings = get_settings()
    try:
        try:
            result = llm_tasks.run_task(TASK, data, model=settings.findings_llm_model or None)
        except (llm_tasks.LLMTaskError, OpenRouterError) as exc:
            if not settings.findings_fallback_model:
                raise
            # Usually a model repeating itself on one input; another model reads it fine.
            log.warning(
                "Findings for order %s failed (%s); trying %s",
                order.id,
                exc,
                settings.findings_fallback_model,
            )
            result = llm_tasks.run_task(TASK, data, model=settings.findings_fallback_model)
    except (llm_tasks.LLMNotConfiguredError, llm_tasks.LLMTaskError, OpenRouterError) as exc:
        log.warning("Findings for order %s failed: %s", order.id, exc)
        req.requested_at = None
        req.attempts += 1
        req.error = str(exc)[:1000]
        db.commit()
        return "failed"
    inspection_findings.save(
        db,
        operator_id=order.operator_id,
        service_order_id=order.id,
        location_id=order.location_id,
        report_id=None,
        source="extraction",
        findings=result.output,
        model=result.model,
        usage=result.usage,
    )
    db.delete(req)
    db.commit()
    return "extracted"


def mark_crashed(db: Session, service_order_id: uuid.UUID) -> None:
    req = db.get(InspectionFindingRequest, service_order_id)
    if req is None:
        return
    req.requested_at = None
    req.attempts += 1
    req.error = "Extraction failed unexpectedly; see the worker log"
    db.commit()


# --- Backfill -------------------------------------------------------------------------------


@dataclass
class Backfill:
    worked: int  # the company's worked orders
    readable: int  # ... with something to read
    done: int  # ... with findings already (from a report draft, or extracted by these rules)
    waiting: int  # ... already queued or failed
    queued: int  # ... queued now (or that would be, on a dry run)


def backfill(
    db: Session, company: Company, *, limit: int | None = None, dry_run: bool = False
) -> Backfill:
    """Queue the company's worked orders that have something to read and no current findings,
    newest first, ready at once. Doesn't commit."""
    worked = (
        select(ServiceOrder.id)
        .join(BillTo, BillTo.id == ServiceOrder.bill_to_id)
        .where(BillTo.company_id == company.id, ServiceOrder.posted.is_(True))
    )
    readable = worked.where(has_something_to_read())
    done = exists().where(
        InspectionFinding.service_order_id == ServiceOrder.id,
        or_(
            InspectionFinding.source == "report_draft",
            InspectionFinding.method_version >= inspection_findings.METHOD_VERSION,
        ),
    )
    waiting = exists().where(InspectionFindingRequest.service_order_id == ServiceOrder.id)
    todo = (
        readable.where(~done, ~waiting)
        .order_by(ServiceOrder.work_date.desc().nulls_last(), ServiceOrder.id)
        .limit(limit)
    )

    def count(query) -> int:
        return db.scalar(select(func.count()).select_from(query.subquery()))

    ids = list(db.scalars(todo))
    if not dry_run:
        request(db, company.operator_id, ids, wait=False)
    return Backfill(
        worked=count(worked),
        readable=count(readable),
        done=count(readable.where(done)),
        waiting=count(readable.where(waiting, ~done)),
        queued=len(ids),
    )
