"""Our copy of PestPac service orders.

PestPac only lists *open* orders, per location (`GET /Locations/{id}/serviceOrders`); once an
order is billed it disappears there and `GET /ServiceOrders/{id}` stops returning it. So:

- An order PestPac returns is upserted. `Posted` flipping to true means it was worked.
- An order of ours that PestPac no longer lists for its location is marked closed (billed).
- Rows are never deleted: after billing, this copy is the only service history left.
- Only orders whose BillToID is an onboarded, active bill-to of the operator are stored.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import requests
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.integrations.pestpac import PestPacAuthError, PestPacClient
from app.models import BillTo, Invoice, Location, ServiceOrder, Technician
from app.schemas.pestpac import PestPacServiceOrderDetails, ServiceOrderSyncCounts
from app.schemas.tenancy import LocationRead
from app.services.pestpac_connection import PestPacUnavailableError
from app.services.technicians import TechnicianResolver


def _json(response: requests.Response) -> object:
    try:
        return response.json()
    except ValueError:
        return None


def fetch_location_orders(
    client: PestPacClient, pestpac_location_id: int
) -> list[PestPacServiceOrderDetails]:
    """All open orders PestPac lists for a location (the endpoint is not paged)."""
    try:
        response = client.service_orders.list_for_location(pestpac_location_id)
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
    if response.status_code != 200:
        # Including 404: treating "location not found" as "no open orders" would close them all.
        raise PestPacUnavailableError(
            f"PestPac /Locations/{pestpac_location_id}/serviceOrders returned "
            f"{response.status_code}"
        )
    body = _json(response)
    if not isinstance(body, list) or not all(
        isinstance(o, dict) and {"OrderID", "LocationID", "BillToID"} <= o.keys() for o in body
    ):
        raise PestPacUnavailableError("PestPac returned an unexpected service orders response")
    orders = [PestPacServiceOrderDetails.from_api(o) for o in body]
    for order in orders:
        if order.pestpac_location_id != pestpac_location_id:
            raise PestPacUnavailableError(
                f"PestPac listed order {order.pestpac_order_id} under location "
                f"{pestpac_location_id}, but it belongs to {order.pestpac_location_id}"
            )
    return orders


def fetch_order(client: PestPacClient, pestpac_order_id: int) -> PestPacServiceOrderDetails | None:
    """The order's current state, or None once PestPac no longer returns it (billed)."""
    try:
        response = client.service_orders.get(pestpac_order_id)
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise PestPacUnavailableError(f"PestPac /ServiceOrders returned {response.status_code}")
    body = _json(response)
    if not isinstance(body, dict) or body.get("OrderID") != pestpac_order_id:
        raise PestPacUnavailableError("PestPac returned an unexpected service order response")
    return PestPacServiceOrderDetails.from_api(body)


def _onboarded_bill_to(db: Session, operator_id: uuid.UUID, pestpac_bill_to_id: int):
    return db.scalar(
        select(BillTo).where(
            BillTo.operator_id == operator_id,
            BillTo.pestpac_bill_to_id == pestpac_bill_to_id,
            BillTo.is_active.is_(True),
        )
    )


def upsert_order(
    db: Session,
    operator_id: uuid.UUID,
    details: PestPacServiceOrderDetails,
    counts: ServiceOrderSyncCounts,
    *,
    now: datetime,
    event_at: datetime | None = None,
    technicians: TechnicianResolver | None = None,
) -> ServiceOrder | None:
    """Store PestPac's current state of an order. Returns None (and counts it as skipped) when
    its BillToID isn't an onboarded, active bill-to. Does not commit."""
    bill_to = _onboarded_bill_to(db, operator_id, details.pestpac_bill_to_id)
    if bill_to is None:
        counts.skipped_other_bill_to += 1
        return None

    # Before the order joins the session: resolving may flush a new technician, and a pending,
    # half-filled order must not be flushed with it.
    technician_id = (
        technicians.resolve(details.tech_id, counts) if technicians is not None else None
    )

    order = db.scalar(
        select(ServiceOrder).where(
            ServiceOrder.operator_id == operator_id,
            ServiceOrder.pestpac_order_id == details.pestpac_order_id,
        )
    )
    if order is None:
        order = ServiceOrder(
            operator_id=operator_id, pestpac_order_id=details.pestpac_order_id, posted=False
        )
        db.add(order)
        counts.added += 1
    else:
        counts.updated += 1
        if order.closed_at is not None:
            # PestPac is listing it again (e.g. a billing was reversed).
            order.closed_at = None
            counts.reopened += 1

    if details.posted and not order.posted:
        order.posted_at = now
        counts.newly_posted += 1
    elif not details.posted:
        order.posted_at = None

    order.bill_to_id = bill_to.id
    order.location_id = db.scalar(
        select(Location.id).where(
            Location.operator_id == operator_id,
            Location.pestpac_location_id == details.pestpac_location_id,
        )
    )
    for field in PestPacServiceOrderDetails.model_fields:
        if field != "pestpac_bill_to_id":
            setattr(order, field, getattr(details, field))
    order.technician_id = technician_id
    order.pestpac_fetched_at = now
    if event_at is not None:
        order.last_event_at = event_at
    return order


def close_order(order: ServiceOrder, counts: ServiceOrderSyncCounts, *, now: datetime) -> None:
    if order.closed_at is None:
        order.closed_at = now
        counts.closed += 1


def sync_location(
    db: Session,
    client: PestPacClient,
    location: Location,
    technicians: TechnicianResolver | None = None,
) -> ServiceOrderSyncCounts:
    """Upsert a location's open orders and close ours that PestPac no longer lists.
    Fetches before writing; does not commit."""
    fetched = fetch_location_orders(client, location.pestpac_location_id)
    now = datetime.now(UTC)
    counts = ServiceOrderSyncCounts()
    for details in fetched:
        upsert_order(db, location.operator_id, details, counts, now=now, technicians=technicians)

    listed = {d.pestpac_order_id for d in fetched}
    still_open = db.scalars(
        select(ServiceOrder).where(
            ServiceOrder.operator_id == location.operator_id,
            ServiceOrder.pestpac_location_id == location.pestpac_location_id,
            ServiceOrder.closed_at.is_(None),
        )
    )
    for order in still_open:
        if order.pestpac_order_id not in listed:
            close_order(order, counts, now=now)
    db.flush()
    return counts


def list_orders(
    db: Session,
    *,
    bill_to_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    status: str = "open",
    limit: int = 200,
    oldest_first: bool = False,
) -> list[ServiceOrder]:
    query = select(ServiceOrder)
    if bill_to_id is not None:
        query = query.where(ServiceOrder.bill_to_id == bill_to_id)
    if location_id is not None:
        query = query.where(ServiceOrder.location_id == location_id)
    if status == "open":
        query = query.where(ServiceOrder.closed_at.is_(None))
    elif status == "closed":
        query = query.where(ServiceOrder.closed_at.is_not(None))
    orders = list(
        db.scalars(
            query.options(selectinload(ServiceOrder.technician))
            .order_by(ServiceOrder.work_date.desc().nulls_last(), ServiceOrder.id)
            .limit(limit)
        )
    )
    if oldest_first:
        # Keep the newest `limit` orders, shown oldest first; undated ones stay last.
        dated = [o for o in orders if o.work_date is not None]
        orders = dated[::-1] + [o for o in orders if o.work_date is None]
    return orders


OrderListState = Literal["posted", "open"]


def _posted_orders(
    bill_to_id: uuid.UUID | None, company_id: uuid.UUID | None, state: OrderListState = "posted"
):
    """For one bill-to or a whole company: `posted`, worked orders without a stored invoice;
    `open`, orders not worked yet that PestPac still lists."""
    if state == "posted":
        query = select(ServiceOrder).where(
            ServiceOrder.posted.is_(True),
            ~exists().where(Invoice.service_order_id == ServiceOrder.id),
        )
    else:
        query = select(ServiceOrder).where(
            ServiceOrder.posted.is_(False), ServiceOrder.closed_at.is_(None)
        )
    if bill_to_id is not None:
        query = query.where(ServiceOrder.bill_to_id == bill_to_id)
    if company_id is not None:
        query = query.where(
            ServiceOrder.bill_to_id.in_(select(BillTo.id).where(BillTo.company_id == company_id))
        )
    return query


def escape_like(q: str) -> str:
    """`q` with LIKE wildcards made literal (the default escape character is backslash)."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_posted_orders(
    db: Session,
    *,
    bill_to_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    q: str | None = None,
    technician_id: uuid.UUID | None = None,
    service_code: str | None = None,
    state: OrderListState = "posted",
    newest_first: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[ServiceOrder, str | None]], int]:
    """Worked orders without a stored invoice (or, with `state="open"`, orders not worked yet),
    by WorkDate (oldest first unless `newest_first`; undated last), with their location's name.
    Invoiced ones are listed from their invoices instead (`invoices.list_invoices`).

    `q` matches the order number or OrderID exactly, or the location's name (which carries the
    store number) anywhere."""
    query = _posted_orders(bill_to_id, company_id, state).outerjoin(
        Location, Location.id == ServiceOrder.location_id
    )
    if q and q.strip():
        q = q.strip()
        match = or_(
            ServiceOrder.order_number == q,
            Location.pestpac_company.ilike(f"%{escape_like(q)}%"),
        )
        if q.isdigit():
            match = or_(match, ServiceOrder.pestpac_order_id == int(q))
        query = query.where(match)
    if technician_id is not None:
        query = query.where(ServiceOrder.technician_id == technician_id)
    if service_code is not None:
        query = query.where(ServiceOrder.service_code == service_code)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(
        query.add_columns(Location.pestpac_company)
        .options(selectinload(ServiceOrder.technician))
        .order_by(
            (
                ServiceOrder.work_date.desc() if newest_first else ServiceOrder.work_date.asc()
            ).nulls_last(),
            ServiceOrder.id,
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return [(order, name) for order, name in rows], total


def posted_order_facets(
    db: Session,
    *,
    bill_to_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    state: OrderListState = "posted",
) -> tuple[list[tuple[uuid.UUID, str]], list[str]]:
    """The technicians (id, name) and service codes among the unfiltered posted (or open)
    orders, for the list's filter choices. Technicians not yet resolved from PestPac aren't
    offered."""
    orders = _posted_orders(bill_to_id, company_id, state).subquery()
    techs = db.execute(
        select(Technician)
        .where(Technician.id.in_(select(orders.c.technician_id)))
        .order_by(Technician.first_name, Technician.last_name)
    ).scalars()
    codes = db.scalars(
        select(orders.c.service_code)
        .where(orders.c.service_code.is_not(None))
        .distinct()
        .order_by(orders.c.service_code)
    )
    return [(t.id, _technician_name(t)) for t in techs], list(codes)


def _technician_name(t: Technician) -> str:
    full = " ".join(p for p in (t.first_name, t.last_name) if p)
    return full or t.username or f"TechID {t.pestpac_tech_id}"


@dataclass(frozen=True)
class LocationOrderStats:
    # Orders PestPac still lists (open or worked, not yet billed).
    open: int = 0
    # Of those, the ones already worked: awaiting billing.
    worked: int = 0
    # WorkDate of the latest worked order, billed or not (PestPac wall-clock time).
    last_service_at: datetime | None = None


def location_order_stats(
    db: Session, location_ids: list[uuid.UUID]
) -> dict[uuid.UUID, LocationOrderStats]:
    if not location_ids:
        return {}
    unbilled = ServiceOrder.closed_at.is_(None)
    rows = db.execute(
        select(
            ServiceOrder.location_id,
            func.count().filter(unbilled),
            func.count().filter(unbilled, ServiceOrder.posted),
            func.max(ServiceOrder.work_date).filter(ServiceOrder.posted),
        )
        .where(ServiceOrder.location_id.in_(location_ids))
        .group_by(ServiceOrder.location_id)
    ).all()
    return {
        loc_id: LocationOrderStats(open=o, worked=w, last_service_at=last)
        for loc_id, o, w, last in rows
    }


def location_read(location: Location, stats: dict[uuid.UUID, LocationOrderStats]) -> LocationRead:
    s = stats.get(location.id, LocationOrderStats())
    return LocationRead.model_validate(location).model_copy(
        update={
            "open_order_count": s.open,
            "worked_order_count": s.worked,
            "last_service_at": s.last_service_at,
        }
    )
