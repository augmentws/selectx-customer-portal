"""PestPac notes for a location: full history, two-step fetch.

1. GET /Locations/{id}/notes (skip/take paged) lists the notes, without associations.
2. GET /Notes/{id} gives a new note's associations (OrderID, InvoiceID, ...). It's called once
   per note, plus re-checks for posted orders still waiting on an InvoiceID.
"""

import uuid
from datetime import UTC, datetime

import requests
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.integrations.pestpac import PestPacAPISection, PestPacAuthError, PestPacClient
from app.models import BillTo, Location, Note, ServiceOrder
from app.schemas.pestpac import NoteSyncCounts, PestPacNoteContent, PestPacNoteDetails
from app.services.pestpac_connection import PestPacUnavailableError
from app.services.technicians import technician_id_for_username


def _get(section: PestPacAPISection, *, params: dict | None = None) -> requests.Response:
    try:
        return section.get(params=params)
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc


def fetch_location_notes(
    client: PestPacClient, pestpac_location_id: int
) -> list[PestPacNoteContent]:
    """Every note PestPac lists for a location. A short page ends paging."""
    settings = get_settings()
    take = settings.pestpac_page_size
    section = client.custom_endpoint(f"/Locations/{pestpac_location_id}/notes")
    by_id: dict[int, PestPacNoteContent] = {}
    for page_number in range(settings.pestpac_max_pages):
        response = _get(section, params={"skip": page_number * take, "take": take})
        if response.status_code != 200:
            raise PestPacUnavailableError(
                f"PestPac /Locations/{pestpac_location_id}/notes returned {response.status_code}"
            )
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, list) or not all(
            isinstance(n, dict) and "NoteID" in n for n in body
        ):
            raise PestPacUnavailableError("PestPac returned an unexpected notes response")
        page = [PestPacNoteContent.from_api(n) for n in body]
        if page and page[0].pestpac_note_id in by_id:
            raise PestPacUnavailableError(
                "PestPac returned the same page of notes twice; paging is not advancing"
            )
        by_id.update({n.pestpac_note_id: n for n in page})
        if len(page) < take:
            return list(by_id.values())
    raise PestPacUnavailableError(
        f"Location {pestpac_location_id} has more than {settings.pestpac_max_pages * take} "
        "notes; raise PESTPAC_MAX_PAGES to sync them"
    )


def fetch_note(client: PestPacClient, pestpac_note_id: int) -> PestPacNoteDetails | None:
    """A note with its associations, or None if PestPac no longer has it."""
    response = _get(client.custom_endpoint(f"/Notes/{pestpac_note_id}"))
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise PestPacUnavailableError(f"PestPac /Notes returned {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("NoteID") != pestpac_note_id:
        raise PestPacUnavailableError("PestPac returned an unexpected note response")
    return PestPacNoteDetails.from_api(body)


def _apply_content(db: Session, note: Note, content: PestPacNoteContent, now: datetime) -> None:
    for field, value in content.model_dump(exclude={"associations"}).items():
        setattr(note, field, value)
    note.created_by_technician_id = technician_id_for_username(
        db, note.operator_id, content.created_by_user
    )
    note.pestpac_fetched_at = now


def _apply_associations(
    db: Session, note: Note, details: PestPacNoteDetails, location: Location, now: datetime
) -> None:
    for column, value in details.associations.items():
        setattr(note, column, value)
    note.associations_fetched_at = now
    # Listed under this location, so it's this location's note even if PestPac's association
    # names a different (or no) LocationID.
    note.location_id = location.id
    note.pestpac_location_id = note.pestpac_location_id or location.pestpac_location_id
    if note.pestpac_bill_to_id is not None:
        note.bill_to_id = db.scalar(
            select(BillTo.id).where(
                BillTo.operator_id == note.operator_id,
                BillTo.pestpac_bill_to_id == note.pestpac_bill_to_id,
            )
        )


def link_notes_to_orders(db: Session, operator_id: uuid.UUID, counts: NoteSyncCounts) -> None:
    """Point notes at our service orders by OrderID, and copy InvoiceIDs onto the orders."""
    linked = db.execute(
        update(Note)
        .where(
            Note.operator_id == operator_id,
            Note.service_order_id.is_(None),
            Note.pestpac_order_id.is_not(None),
            ServiceOrder.operator_id == operator_id,
            ServiceOrder.pestpac_order_id == Note.pestpac_order_id,
        )
        .values(service_order_id=ServiceOrder.id)
        .execution_options(synchronize_session=False)
    )
    counts.linked_to_orders += linked.rowcount or 0
    invoiced = db.execute(
        update(ServiceOrder)
        .where(
            ServiceOrder.operator_id == operator_id,
            ServiceOrder.pestpac_invoice_id.is_(None),
            Note.service_order_id == ServiceOrder.id,
            Note.pestpac_invoice_id.is_not(None),
        )
        .values(pestpac_invoice_id=Note.pestpac_invoice_id)
        .execution_options(synchronize_session=False)
    )
    counts.invoices_found += invoiced.rowcount or 0


def sync_location_notes(db: Session, client: PestPacClient, location: Location) -> NoteSyncCounts:
    """Store the location's full note history. Does not commit."""
    listed = fetch_location_notes(client, location.pestpac_location_id)
    now = datetime.now(UTC)
    counts = NoteSyncCounts(total=len(listed))
    existing = {
        n.pestpac_note_id: n
        for n in db.scalars(
            select(Note).where(
                Note.operator_id == location.operator_id,
                Note.pestpac_note_id.in_([n.pestpac_note_id for n in listed]),
            )
        )
    }
    for content in listed:
        note = existing.get(content.pestpac_note_id)
        if note is not None:
            _apply_content(db, note, content, now)  # text may have been edited
            counts.updated += 1
            continue
        details = fetch_note(client, content.pestpac_note_id)
        counts.details_fetched += 1
        if details is None:
            continue  # deleted between the two calls
        note = Note(operator_id=location.operator_id, pestpac_note_id=details.pestpac_note_id)
        db.add(note)
        _apply_content(db, note, details, now)
        _apply_associations(db, note, details, location, now)
        counts.added += 1

    # Invoices arrive after posting: re-check notes of posted orders still without one.
    waiting = db.scalars(
        select(Note)
        .join(ServiceOrder, ServiceOrder.id == Note.service_order_id)
        .where(
            Note.location_id == location.id,
            ServiceOrder.posted.is_(True),
            ServiceOrder.pestpac_invoice_id.is_(None),
            Note.pestpac_invoice_id.is_(None),
        )
    ).all()
    for note in waiting:
        details = fetch_note(client, note.pestpac_note_id)
        counts.details_fetched += 1
        if details is not None:
            _apply_associations(db, note, details, location, now)

    db.flush()
    link_notes_to_orders(db, location.operator_id, counts)
    db.flush()
    return counts


def list_notes(
    db: Session,
    *,
    location_id: uuid.UUID | None = None,
    service_order_id: uuid.UUID | None = None,
) -> list[Note]:
    query = select(Note)
    if location_id is not None:
        query = query.where(Note.location_id == location_id)
    if service_order_id is not None:
        query = query.where(Note.service_order_id == service_order_id)
    return list(
        db.scalars(
            query.options(selectinload(Note.created_by_technician)).order_by(
                Note.note_date.desc().nulls_last(), Note.id
            )
        )
    )
