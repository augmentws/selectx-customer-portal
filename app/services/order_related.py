"""What was logged around a service order, for its page.

PestPac links few documents, conditions, and notes to an order, so as with service reports the
location's items dated within a day of the work date are included too, marked "same_day".
Linked items come first; an item is listed once, under its closest link.
"""

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Condition, ConditionInspection, Document, Invoice, Note, ServiceOrder
from app.schemas.tenancy import (
    ConditionBase,
    DocumentRead,
    NoteRead,
    OrderCondition,
    OrderDocument,
    OrderNote,
    ServiceOrderRelated,
)
from app.services.conditions import documents_by_condition
from app.services.service_reports import same_day_window


def stored_invoice_id(db: Session, order: ServiceOrder) -> uuid.UUID | None:
    return db.scalar(
        select(Invoice.id)
        .where(Invoice.service_order_id == order.id, Invoice.removed_at.is_(None))
        .limit(1)
    )


def _documents(db: Session, order: ServiceOrder, window) -> list[OrderDocument]:
    # By our link or PestPac's OrderID: documents of an order stored after them only carry the
    # raw id. Condition documents are listed under their conditions instead.
    linked = or_(
        Document.service_order_id == order.id,
        and_(
            Document.operator_id == order.operator_id,
            Document.pestpac_order_id == order.pestpac_order_id,
        ),
    )
    match = linked
    if window and order.location_id is not None:
        same_day = and_(
            Document.location_id == order.location_id, Document.document_date.between(*window)
        )
        match = or_(linked, same_day)
    rows = db.scalars(
        select(Document)
        .where(match, Document.removed_at.is_(None), Document.condition_id.is_(None))
        .order_by(Document.document_date.nulls_last(), Document.id)
    ).all()
    items = [
        OrderDocument(
            **DocumentRead.model_validate(d).model_dump(),
            link="order"
            if d.service_order_id == order.id or d.pestpac_order_id == order.pestpac_order_id
            else "same_day",
        )
        for d in rows
    ]
    return sorted(items, key=lambda i: i.link != "order")


def _conditions(db: Session, order: ServiceOrder, window) -> list[OrderCondition]:
    def on_order(model):
        return or_(
            model.service_order_id == order.id, model.pestpac_order_id == order.pestpac_order_id
        )

    inspected_on_order = select(ConditionInspection.condition_id).where(
        on_order(ConditionInspection)
    )
    match = or_(on_order(Condition), Condition.id.in_(inspected_on_order))
    if window and order.location_id is not None:
        inspected_that_day = select(ConditionInspection.condition_id).where(
            ConditionInspection.detail_date.between(*window)
        )
        match = or_(
            match,
            and_(
                Condition.location_id == order.location_id,
                or_(
                    Condition.date_opened.between(*window),
                    Condition.id.in_(inspected_that_day),
                ),
            ),
        )
    rows = db.scalars(
        select(Condition)
        .where(match, Condition.operator_id == order.operator_id, Condition.removed_at.is_(None))
        .options(selectinload(Condition.inspections))
        .order_by(Condition.date_opened.nulls_last(), Condition.id)
    ).all()
    docs = documents_by_condition(db, [c.id for c in rows])

    def link(c: Condition) -> str:
        if c.service_order_id == order.id or c.pestpac_order_id == order.pestpac_order_id:
            return "opened"
        if any(
            i.service_order_id == order.id or i.pestpac_order_id == order.pestpac_order_id
            for i in c.inspections
        ):
            return "inspected"
        return "same_day"

    items = [
        OrderCondition(
            **ConditionBase.model_validate(c).model_dump(),
            documents=[DocumentRead.model_validate(d) for d in docs.get(c.id, [])],
            link=link(c),
        )
        for c in rows
    ]
    return sorted(items, key=lambda i: i.link == "same_day")


def _notes(db: Session, order: ServiceOrder, window) -> list[OrderNote]:
    match = Note.service_order_id == order.id
    if window and order.location_id is not None:
        match = or_(
            match, and_(Note.location_id == order.location_id, Note.note_date.between(*window))
        )
    rows = db.scalars(
        select(Note)
        .where(match)
        .options(selectinload(Note.created_by_technician))
        .order_by(Note.note_date.nulls_last(), Note.id)
    ).all()
    items = [
        OrderNote(
            **NoteRead.model_validate(n).model_dump(),
            link="order" if n.service_order_id == order.id else "same_day",
        )
        for n in rows
    ]
    return sorted(items, key=lambda i: i.link != "order")


def related(db: Session, order: ServiceOrder) -> ServiceOrderRelated:
    window = same_day_window(order.work_date)
    return ServiceOrderRelated(
        documents=_documents(db, order, window),
        conditions=_conditions(db, order, window),
        notes=_notes(db, order, window),
    )
