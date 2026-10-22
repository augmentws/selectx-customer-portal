"""Our copy of PestPac service orders.

PestPac only lists *open* orders, per location (`GET /Locations/{id}/serviceOrders`); once an
order is billed it disappears there and `GET /ServiceOrders/{id}` stops returning it. So:

- An order PestPac returns is upserted. `Posted` flipping to true means it was worked.
- An order of ours that PestPac no longer lists for its location is marked closed (billed).
- Rows are never deleted: after billing, this copy is the only service history left.
- Only orders whose BillToID is an onboarded, active bill-to of the operator are stored.
"""

import uuid
from datetime import UTC, datetime

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.integrations.pestpac import PestPacAuthError, PestPacClient
from app.models import BillTo, Location, ServiceOrder
from app.schemas.pestpac import PestPacServiceOrderDetails, ServiceOrderSyncCounts
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
    return list(
        db.scalars(
            query.options(selectinload(ServiceOrder.technician))
            .order_by(ServiceOrder.work_date.desc().nulls_last(), ServiceOrder.id)
            .limit(limit)
        )
    )


def open_order_counts(db: Session, location_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not location_ids:
        return {}
    rows = db.execute(
        select(ServiceOrder.location_id, func.count())
        .where(ServiceOrder.location_id.in_(location_ids), ServiceOrder.closed_at.is_(None))
        .group_by(ServiceOrder.location_id)
    ).all()
    return dict(rows)
