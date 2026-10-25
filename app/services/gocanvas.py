"""GoCanvas webhook capture (stub): every request to an operator's URL is stored as received.

Nothing is processed until GoCanvas's format is known. Credentials in headers are never stored.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import GoCanvasRequest, Tenant, TenantKind
from app.services.webhooks import RequestClient

# Never stored: they may carry credentials.
SECRET_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "api-key"}
)


def receive(
    db: Session,
    operator_id: uuid.UUID,
    *,
    method: str,
    query_string: str,
    headers: list[tuple[str, str]],
    raw: bytes,
    client: RequestClient,
) -> GoCanvasRequest | None:
    """Store the request if the operator exists and is active (None otherwise). Commits."""
    operator = db.get(Tenant, operator_id)
    if operator is None or operator.kind is not TenantKind.operator or not operator.is_active:
        return None
    kept: dict[str, str] = {}
    for name, value in headers:
        key = name.lower()
        if key not in SECRET_HEADERS:
            kept[key] = f"{kept[key]}, {value}" if key in kept else value
    request = GoCanvasRequest(
        operator_id=operator.id,
        method=method.upper()[:10],
        query_string=query_string[:2000] or None,
        content_type=(kept.get("content-type") or "")[:200] or None,
        headers=kept,
        body_size=len(raw),
        body_sha256=hashlib.sha256(raw).hexdigest(),
        raw_body=raw.decode("utf-8", errors="replace"),
        **client.columns(),
    )
    db.add(request)
    db.commit()
    return request


def list_requests(
    db: Session, operator_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> tuple[list[GoCanvasRequest], int]:
    """An operator's received requests, newest first."""
    query = select(GoCanvasRequest).where(GoCanvasRequest.operator_id == operator_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(GoCanvasRequest.received_at.desc(), GoCanvasRequest.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total


def purge_raw_bodies(db: Session, now: datetime | None = None) -> int:
    """Clear raw bodies older than the retention window. Commits; returns how many."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=get_settings().webhook_raw_retention_days)
    result = db.execute(
        update(GoCanvasRequest)
        .where(GoCanvasRequest.received_at < cutoff, GoCanvasRequest.raw_body.is_not(None))
        .values(raw_body=None, raw_body_purged_at=now)
    )
    db.commit()
    return result.rowcount
