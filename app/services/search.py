"""Header search across the records a caller can open.

Names match anywhere (case-insensitive); PestPac ids and order/invoice numbers match exactly.
Each kind is searched only on the operators where the caller holds the permission its page
needs, so a hit never leads to a 404 or reveals another operator's records.
"""

import uuid

from sqlalchemy import Select, false, or_, select
from sqlalchemy.orm import Session

from app.models import BillTo, Company, Invoice, Location, ServiceOrder, Tenant, TenantKind
from app.schemas.search import SearchHit
from app.security.access import AccessScope
from app.security.permissions import Perm
from app.services.trail import location_name


def _like(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _scoped(query: Select, column, operator_ids: set[uuid.UUID] | None) -> Select:
    """`operator_ids=None` means every operator."""
    if operator_ids is None:
        return query
    return query.where(column.in_(operator_ids)) if operator_ids else query.where(false())


def _place(row: Location | BillTo) -> str | None:
    return ", ".join(p for p in (row.address, row.city, row.state) if p) or None


def search(db: Session, scope: AccessScope, q: str, *, limit: int) -> list[SearchHit]:
    q = q.strip()
    like = _like(q)
    number = int(q) if q.isdigit() else None
    hits: list[SearchHit] = []

    if scope.has_anywhere(Perm.operators_read):
        query = select(Tenant).where(Tenant.kind == TenantKind.operator, Tenant.name.ilike(like))
        query = _scoped(query, Tenant.id, scope.operator_ids_with(Perm.operators_read))
        for t in db.scalars(query.order_by(Tenant.name).limit(limit)):
            hits.append(SearchHit(kind="operator", id=t.id, title=t.name))

    if scope.has_anywhere(Perm.companies_read):
        query = select(Company).where(Company.name.ilike(like))
        query = _scoped(query, Company.operator_id, scope.operator_ids_with(Perm.companies_read))
        query = query.order_by(Company.is_active.desc(), Company.name).limit(limit)
        for c in db.scalars(query):
            hits.append(SearchHit(kind="company", id=c.id, title=c.name))

    if not scope.has_anywhere(Perm.bill_tos_read):
        return hits
    bill_to_ops = scope.operator_ids_with(Perm.bill_tos_read)

    match = BillTo.name.ilike(like)
    if number is not None:
        match = or_(match, BillTo.pestpac_bill_to_id == number)
    query = select(BillTo, Company.name).join(Company, Company.id == BillTo.company_id)
    query = _scoped(query.where(match), BillTo.operator_id, bill_to_ops)
    for b, company in db.execute(query.order_by(BillTo.is_active.desc(), BillTo.name).limit(limit)):
        hits.append(
            SearchHit(
                kind="bill_to",
                id=b.id,
                title=b.name,
                detail=f"{company} · BillToID {b.pestpac_bill_to_id}",
            )
        )

    match = or_(
        Location.pestpac_company.ilike(like),
        Location.address.ilike(like),
        Location.city.ilike(like),
        Location.pestpac_location_code == q,
    )
    if number is not None:
        match = or_(match, Location.pestpac_location_id == number)
    query = _scoped(select(Location).where(match), Location.operator_id, bill_to_ops)
    query = query.order_by(Location.removed_at.is_not(None), Location.pestpac_company)
    for loc in db.scalars(query.limit(limit)):
        hits.append(
            SearchHit(kind="location", id=loc.id, title=location_name(loc), detail=_place(loc))
        )

    match = ServiceOrder.order_number == q
    if number is not None:
        match = or_(match, ServiceOrder.pestpac_order_id == number)
    query = select(ServiceOrder, Location).join(Location, Location.id == ServiceOrder.location_id)
    query = _scoped(query.where(match), ServiceOrder.operator_id, bill_to_ops)
    for order, loc in db.execute(query.order_by(ServiceOrder.work_date.desc()).limit(limit)):
        hits.append(
            SearchHit(
                kind="service_order",
                id=order.id,
                title=f"Order {order.order_number or order.pestpac_order_id}",
                detail=location_name(loc),
                location_id=loc.id,
            )
        )

    if scope.has_anywhere(Perm.billing_read):
        match = Invoice.invoice_number == q
        if number is not None:
            match = or_(match, Invoice.pestpac_invoice_id == number)
        query = select(Invoice, Location).join(Location, Location.id == Invoice.location_id)
        query = _scoped(
            query.where(match), Invoice.operator_id, scope.operator_ids_with(Perm.billing_read)
        )
        for inv, loc in db.execute(query.order_by(Invoice.invoice_date.desc()).limit(limit)):
            hits.append(
                SearchHit(
                    kind="invoice",
                    id=inv.id,
                    title=f"Invoice {inv.invoice_number or inv.pestpac_invoice_id}",
                    detail=location_name(loc),
                    location_id=loc.id,
                )
            )
    return hits
