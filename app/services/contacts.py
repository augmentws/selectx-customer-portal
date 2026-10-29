"""Contacts supplied by the customer, and the Restaurant Leader Report import.

The Leader Report is Chipotle's export of every restaurant with its leaders. Only OPEN stores
that match a location we already hold are imported (PROJECT stores are ignored); each match gets
up to four contacts (the store itself, its Executive Team Director, Team Director, and
Restaurant Leader) and its `description` set to the report's store name.
"""

import re
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import BillTo, Contact, ContactLink, ContactRole, Location

LEADER_REPORT = "restaurant_leader_report"

# The report's columns by position. Its header row isn't the first line (the export sorts it
# in among the stores), so it's found and checked against these before anything is imported.
NUMBER, NAME, STATUS, STORE_PHONE, STORE_EMAIL = 0, 1, 3, 5, 15
PEOPLE = {
    ContactRole.executive_team_director: 21,
    ContactRole.team_director: 24,
    ContactRole.restaurant_leader: 27,
}
HEADER = {
    NUMBER: "Restaurant Number",
    NAME: "Restaurant Name Number",
    STATUS: "Restaurant Status",
    STORE_PHONE: "Phone Number",
    STORE_EMAIL: "Email Address",
    21: "Executive Team Director",
    24: "Team Director",
    27: "Area Manager / Team Leader / Apprentice Team Leader",
}
STORE_NUMBER = re.compile(r"#\s*(\d+)\s*$")
# Lists show the store first, then its leaders from the top down.
ROLE_ORDER = [
    ContactRole.store,
    ContactRole.executive_team_director,
    ContactRole.team_director,
    ContactRole.restaurant_leader,
]


class LeaderReportError(ValueError):
    """The file isn't the Leader Report layout this importer knows."""


@dataclass
class LeaderReportResult:
    rows: int = 0
    # Restaurant status of rows not imported (PROJECT, ...): count.
    skipped_status: Counter[str] = field(default_factory=Counter)
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)
    # Store numbers that match more than one of our locations.
    ambiguous: list[str] = field(default_factory=list)
    descriptions_changed: int = 0
    contacts: Counter[str] = field(default_factory=Counter)
    links: Counter[str] = field(default_factory=Counter)


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _cell(row: Sequence[str], index: int) -> str | None:
    return _clean(row[index]) if index < len(row) else None


def _is_header(row: Sequence[str]) -> bool:
    return _cell(row, NUMBER) == HEADER[NUMBER]


def _check_header(rows: Sequence[Sequence[str]]) -> None:
    headers = [row for row in rows if _is_header(row)]
    if len(headers) != 1:
        raise LeaderReportError(f"expected one header row, found {len(headers)}")
    wrong = {
        expected: _cell(headers[0], index)
        for index, expected in HEADER.items()
        if _cell(headers[0], index) != expected
    }
    if wrong:
        raise LeaderReportError(f"unexpected columns (expected: found): {wrong}")


def _locations_by_store(db: Session, operator_id: uuid.UUID, company_id: uuid.UUID):
    """The company's locations by the store number their name ends with ("... #2301")."""
    by_store: dict[str, list[Location]] = {}
    locations = db.scalars(
        select(Location)
        .join(BillTo, BillTo.id == Location.bill_to_id)
        .where(Location.operator_id == operator_id, BillTo.company_id == company_id)
    )
    for location in locations:
        match = STORE_NUMBER.search(location.pestpac_company or "")
        if match:
            by_store.setdefault(match.group(1).lstrip("0"), []).append(location)
    return by_store


def import_leader_report(
    db: Session,
    operator_id: uuid.UUID,
    company_id: uuid.UUID,
    rows: Iterable[Sequence[str]],
) -> LeaderReportResult:
    """Upsert the report's contacts and links for the company's matching locations, and mark
    this source's links the report no longer lists as removed. Doesn't commit."""
    rows = [row for row in rows if len(row) > STATUS]
    _check_header(rows)
    now = datetime.now(UTC)
    result = LeaderReportResult()
    by_store = _locations_by_store(db, operator_id, company_id)

    contacts = {
        c.source_key: c
        for c in db.scalars(
            select(Contact).where(
                Contact.operator_id == operator_id,
                Contact.source == LEADER_REPORT,
                Contact.company_id == company_id,
            )
        )
    }
    links = {
        (link.contact_id, link.location_id, link.role): link
        for link in db.scalars(
            select(ContactLink)
            .join(Contact, Contact.id == ContactLink.contact_id)
            .where(
                ContactLink.operator_id == operator_id,
                ContactLink.source == LEADER_REPORT,
                Contact.company_id == company_id,
            )
        )
    }
    seen_links: set[tuple] = set()

    def upsert_contact(key: str, name: str | None, email: str | None, phone: str | None) -> Contact:
        contact = contacts.get(key)
        if contact is None:
            contact = Contact(
                operator_id=operator_id,
                company_id=company_id,
                source=LEADER_REPORT,
                source_key=key,
                name=name,
                email=email,
                phone=phone,
            )
            db.add(contact)
            db.flush()
            contacts[key] = contact
            result.contacts["created"] += 1
        elif (contact.name, contact.email, contact.phone, contact.removed_at) != (
            name,
            email,
            phone,
            None,
        ):
            contact.name, contact.email, contact.phone = name, email, phone
            contact.removed_at = None
            result.contacts["updated"] += 1
        return contact

    def link(contact: Contact, location: Location, role: ContactRole) -> None:
        key = (contact.id, location.id, role)
        seen_links.add(key)
        existing = links.get(key)
        if existing is None:
            links[key] = ContactLink(
                operator_id=operator_id,
                contact_id=contact.id,
                location_id=location.id,
                role=role,
                source=LEADER_REPORT,
                imported_at=now,
            )
            db.add(links[key])
            result.links["created"] += 1
        else:
            if existing.removed_at is not None:
                result.links["restored"] += 1
            existing.imported_at, existing.removed_at = now, None

    for row in rows:
        if _is_header(row):
            continue
        result.rows += 1
        status = _cell(row, STATUS) or "(blank)"
        if status != "OPEN":
            result.skipped_status[status] += 1
            continue
        number = _cell(row, NUMBER) or ""
        matches = by_store.get(number.lstrip("0"), [])
        if not matches:
            result.unmatched.append(number)
            continue
        if len(matches) > 1:
            result.ambiguous.append(number)
            continue
        location = matches[0]
        result.matched += 1

        name = _cell(row, NAME)
        if name and location.description != name:
            location.description = name
            result.descriptions_changed += 1

        email = _cell(row, STORE_EMAIL)
        store = upsert_contact(
            f"store:{number}", name, email and email.lower(), _cell(row, STORE_PHONE)
        )
        link(store, location, ContactRole.store)
        for role, index in PEOPLE.items():
            person = _cell(row, index)
            if person is None:
                continue
            email, phone = _cell(row, index + 1), _cell(row, index + 2)
            key = email.lower() if email else f"{person.lower()}|{phone or ''}"
            link(upsert_contact(key, person, email and email.lower(), phone), location, role)

    for key, existing in links.items():
        if key not in seen_links and existing.removed_at is None:
            existing.removed_at = now
            result.links["removed"] += 1
    linked = {contact_id for (contact_id, _, _) in seen_links}
    for contact in contacts.values():
        if contact.id not in linked and contact.removed_at is None:
            contact.removed_at = now
            result.contacts["removed"] += 1
    db.flush()
    return result


def _current(db: Session, *where) -> list[ContactLink]:
    found = db.scalars(
        select(ContactLink)
        .join(Contact, Contact.id == ContactLink.contact_id)
        .options(joinedload(ContactLink.contact))
        .where(*where, ContactLink.removed_at.is_(None), Contact.removed_at.is_(None))
    ).all()
    return sorted(found, key=lambda link: (ROLE_ORDER.index(link.role), link.contact.name or ""))


def list_for_location(db: Session, location_id: uuid.UUID) -> list[ContactLink]:
    """The location's current contacts: the store first, then its leaders from the top down."""
    return _current(db, ContactLink.location_id == location_id)


def list_for_bill_to(db: Session, bill_to_id: uuid.UUID) -> list[ContactLink]:
    """Contacts linked to the bill-to itself (not to its locations)."""
    return _current(db, ContactLink.bill_to_id == bill_to_id)
