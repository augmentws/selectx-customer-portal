"""Dashboard aggregates over our service-order copy (stub: service activity only).

A "service" is a worked order (`posted`), dated by its WorkDate. Orders PestPac no longer lists
(`closed_at`) and that were worked count as billed. Totals are calculated in SQL so the
browser receives summaries, not rows. Findings, programs, and risk metrics come later
(docs/customer-dashboard-plan.md).
"""

import re
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import String, and_, cast, distinct, func, select
from sqlalchemy.orm import Session

from app.models import BillTo, Location, ServiceOrder, Technician
from app.schemas.dashboard import (
    CompanyDashboard,
    DashboardHeadline,
    MonthCount,
    ServiceCodeCount,
    StoreRow,
    TechnicianCount,
)

# Months shown when the history is longer than this.
MAX_MONTHS = 24
TOP_TECHNICIANS = 10
_STORE_NUMBER = re.compile(r"#\s*(\d+)")

_worked = ServiceOrder.posted.is_(True)
_open = and_(ServiceOrder.posted.is_(False), ServiceOrder.closed_at.is_(None))


def store_number(name: str | None) -> str | None:
    match = _STORE_NUMBER.search(name or "")
    return match.group(1) if match else None


def _count(condition):
    return func.count().filter(condition)


def _month_range(first: date, last: date) -> list[str]:
    months = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months[-MAX_MONTHS:]


def company_dashboard(
    db: Session, company_id: uuid.UUID, bill_to_id: uuid.UUID | None = None
) -> CompanyDashboard:
    bill_tos = select(BillTo.id).where(BillTo.company_id == company_id)
    if bill_to_id is not None:
        bill_tos = bill_tos.where(BillTo.id == bill_to_id)
    scoped = select(ServiceOrder).where(ServiceOrder.bill_to_id.in_(bill_tos)).subquery()

    totals = db.execute(
        select(
            _count(scoped.c.posted.is_(True)),
            _count(and_(scoped.c.posted.is_(False), scoped.c.closed_at.is_(None))),
            _count(and_(scoped.c.posted.is_(True), scoped.c.closed_at.is_(None))),
            _count(and_(scoped.c.posted.is_(True), scoped.c.closed_at.is_not(None))),
            # A resolved technician, else PestPac's raw Tech1 username.
            func.count(
                distinct(func.coalesce(cast(scoped.c.technician_id, String), scoped.c.tech_name))
            ).filter(scoped.c.posted.is_(True)),
            func.count(distinct(scoped.c.location_id)).filter(scoped.c.posted.is_(True)),
            func.min(scoped.c.work_date).filter(scoped.c.posted.is_(True)),
            func.max(scoped.c.work_date).filter(scoped.c.posted.is_(True)),
        )
    ).one()
    (services, open_orders, awaiting, billed, technicians, serviced, first, last) = totals

    locations = list(
        db.scalars(
            select(Location)
            .where(Location.bill_to_id.in_(bill_tos), Location.removed_at.is_(None))
            .order_by(Location.pestpac_company, Location.id)
        )
    )

    month = func.to_char(ServiceOrder.work_date, "YYYY-MM")
    by_month = dict(
        db.execute(
            select(month, func.count())
            .where(
                ServiceOrder.bill_to_id.in_(bill_tos), _worked, ServiceOrder.work_date.is_not(None)
            )
            .group_by(month)
        ).all()
    )
    months = _month_range(first.date(), last.date()) if first and last else []

    by_code = db.execute(
        select(ServiceOrder.service_code, func.count().label("n"))
        .where(ServiceOrder.bill_to_id.in_(bill_tos), _worked)
        .group_by(ServiceOrder.service_code)
        .order_by(func.count().desc(), ServiceOrder.service_code)
    ).all()

    full_name = func.nullif(
        func.trim(func.concat_ws(" ", Technician.first_name, Technician.last_name)), ""
    )
    by_tech = db.execute(
        select(
            ServiceOrder.technician_id,
            func.coalesce(full_name, ServiceOrder.tech_name).label("name"),
            func.count().label("n"),
        )
        .outerjoin(Technician, Technician.id == ServiceOrder.technician_id)
        .where(ServiceOrder.bill_to_id.in_(bill_tos), _worked)
        .group_by(ServiceOrder.technician_id, "name")
        .order_by(func.count().desc(), "name")
        .limit(TOP_TECHNICIANS)
    ).all()

    per_store = {
        row.location_id: row
        for row in db.execute(
            select(
                ServiceOrder.location_id,
                _count(_worked).label("services"),
                _count(_open).label("open_orders"),
                func.max(ServiceOrder.work_date).filter(_worked).label("last_service"),
            )
            .where(ServiceOrder.bill_to_id.in_(bill_tos), ServiceOrder.location_id.is_not(None))
            .group_by(ServiceOrder.location_id)
        )
    }

    def store(loc: Location) -> StoreRow:
        stats = per_store.get(loc.id)
        return StoreRow(
            location_id=loc.id,
            bill_to_id=loc.bill_to_id,
            pestpac_location_id=loc.pestpac_location_id,
            store_number=store_number(loc.pestpac_company),
            name=loc.pestpac_company,
            city=loc.city,
            state=loc.state,
            latitude=loc.latitude,
            longitude=loc.longitude,
            pestpac_active=loc.pestpac_active,
            services=stats.services if stats else 0,
            open_orders=stats.open_orders if stats else 0,
            last_service=stats.last_service if stats else None,
        )

    return CompanyDashboard(
        company_id=company_id,
        bill_to_id=bill_to_id,
        as_of=datetime.now(UTC),
        headline=DashboardHeadline(
            locations=len(locations),
            locations_serviced=serviced,
            services=services,
            open_orders=open_orders,
            awaiting_billing=awaiting,
            billed=billed,
            technicians=technicians,
            first_service=first,
            last_service=last,
        ),
        services_by_month=[MonthCount(month=m, services=by_month.get(m, 0)) for m in months],
        services_by_code=[ServiceCodeCount(service_code=c, services=n) for c, n in by_code],
        top_technicians=[
            TechnicianCount(technician_id=t, name=name, services=n) for t, name, n in by_tech
        ],
        stores=[store(loc) for loc in locations],
    )
