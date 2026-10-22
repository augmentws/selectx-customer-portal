"""PestPac webhook capture (stub: events are stored, not yet processed).

A delivery is a JSON envelope: TenantId, EntityType ("Service Order", ...), EntityId, Action,
Url, and the record itself in EntityBody. It's signed with HMAC-SHA256 over the serialized
EntityBody followed by the `timestamputc` header, sent in one or more `signature` headers.

Signature checks run in report mode: a bad or missing signature is recorded on the event, not
refused, until the scheme has been confirmed against real PestPac deliveries.

Only events that match the bill-to rule are stored (see `_matches_bill_to_rule`); the rest are
dropped. Stored events stay `received`: the per-entity handlers (re-fetch, upsert, close,
notes collection) are not built yet.
"""

import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    BillTo,
    Location,
    Note,
    PestPacConnection,
    ServiceOrder,
    SignatureStatus,
    Tenant,
    TenantKind,
    WebhookEntity,
    WebhookEvent,
)
from app.security.secrets import decrypt

log = logging.getLogger(__name__)

# PestPac's EntityType, lowercased with spaces removed.
_ENTITY_TYPES = {
    "billto": WebhookEntity.bill_to,
    "employee": WebhookEntity.employee,
    "location": WebhookEntity.location,
    "note": WebhookEntity.note,
    "notes": WebhookEntity.note,
    "serviceorder": WebhookEntity.service_order,
}

# The actions we capture per entity. Planned handling, once built:
# - service_order create/update: upsert from the body; post: mark worked, then collect the
#   location's notes (InvoiceID); delete: mark deleted.
# - location create/update: upsert, or `removed_at` when it moves off our bill-tos; delete:
#   `removed_at`.
# - bill_to update: refresh identifying fields; delete: flag it, don't deactivate.
# - note create/update: upsert and fetch its associations; delete: mark deleted.
# - employee create/update: upsert the technician; delete: mark inactive.
SUPPORTED_ACTIONS: dict[WebhookEntity, frozenset[str]] = {
    WebhookEntity.bill_to: frozenset({"create", "update", "delete"}),
    WebhookEntity.employee: frozenset({"create", "update", "delete"}),
    WebhookEntity.location: frozenset({"create", "update", "delete"}),
    WebhookEntity.note: frozenset({"create", "update", "delete"}),
    WebhookEntity.service_order: frozenset({"create", "update", "post", "delete"}),
}


class InvalidWebhookError(ValueError):
    """The request isn't a PestPac webhook envelope."""


@dataclass(frozen=True)
class Envelope:
    tenant_id: str
    entity: WebhookEntity | None  # None: an EntityType we don't capture
    entity_type: str
    entity_id: int
    action: str
    body: dict | None


def parse_envelope(raw: bytes) -> Envelope:
    try:
        data = json.loads(raw)
    except UnicodeDecodeError, ValueError:
        raise InvalidWebhookError("Body is not valid JSON") from None
    if not isinstance(data, dict):
        raise InvalidWebhookError("Body is not a JSON object")
    tenant_id, entity_type = data.get("TenantId"), data.get("EntityType")
    entity_id, action, body = data.get("EntityId"), data.get("Action"), data.get("EntityBody")
    if not isinstance(tenant_id, str | int) or isinstance(tenant_id, bool) or tenant_id == "":
        raise InvalidWebhookError("TenantId is missing")
    if not isinstance(entity_type, str) or not isinstance(action, str):
        raise InvalidWebhookError("EntityType and Action are required")
    if not isinstance(entity_id, int) or isinstance(entity_id, bool):
        raise InvalidWebhookError("EntityId must be an integer")
    if body is not None and not isinstance(body, dict):
        raise InvalidWebhookError("EntityBody must be an object")
    return Envelope(
        tenant_id=str(tenant_id),
        entity=_ENTITY_TYPES.get(entity_type.replace(" ", "").replace("-", "").lower()),
        entity_type=entity_type,
        entity_id=entity_id,
        action=action.strip().lower(),
        body=body,
    )


def _expected_signatures(secret: str, body: dict | None, timestamp: str) -> list[str]:
    # The serialization PestPac signs isn't confirmed; accept the two plausible ones.
    texts = {json.dumps(body), json.dumps(body, separators=(",", ":"))}
    key = secret.encode()
    return [
        hmac.new(key, (text + timestamp).encode(), hashlib.sha256).hexdigest().upper()
        for text in texts
    ]


def check_signature(
    secret: str | None, body: dict | None, signatures: list[str], timestamp: str | None
) -> SignatureStatus:
    if secret is None:
        return SignatureStatus.no_secret
    if not signatures or not timestamp:
        return SignatureStatus.missing
    expected = _expected_signatures(secret, body, timestamp)
    for given in signatures:
        if any(hmac.compare_digest(given.strip().upper(), e) for e in expected):
            return SignatureStatus.valid
    return SignatureStatus.invalid


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _onboarded(db: Session, operator_id: uuid.UUID, pestpac_bill_to_id: int | None) -> bool:
    if pestpac_bill_to_id is None:
        return False
    return bool(
        db.scalar(
            select(
                exists().where(
                    BillTo.operator_id == operator_id,
                    BillTo.pestpac_bill_to_id == pestpac_bill_to_id,
                    BillTo.is_active.is_(True),
                )
            )
        )
    )


def _known(db: Session, column, operator_column, operator_id: uuid.UUID, value) -> bool:
    if value is None:
        return False
    return bool(db.scalar(select(exists().where(operator_column == operator_id, column == value))))


def _matches_bill_to_rule(db: Session, operator_id: uuid.UUID, env: Envelope) -> bool:
    """Is this event about something on an onboarded bill-to? Deletes may arrive without a
    body, so an entity we already hold also matches."""
    body = env.body or {}
    match env.entity:
        case WebhookEntity.bill_to:
            return _onboarded(db, operator_id, env.entity_id)
        case WebhookEntity.service_order:
            return _onboarded(db, operator_id, _int(body.get("BillToID"))) or _known(
                db, ServiceOrder.pestpac_order_id, ServiceOrder.operator_id, operator_id,
                env.entity_id,
            )  # fmt: skip
        case WebhookEntity.location:
            return _onboarded(db, operator_id, _int(body.get("BillToID"))) or _known(
                db, Location.pestpac_location_id, Location.operator_id, operator_id,
                env.entity_id,
            )  # fmt: skip
        case WebhookEntity.note:
            # Field names in a note webhook body are unconfirmed; LocationID/OrderID assumed.
            return (
                _known(db, Note.pestpac_note_id, Note.operator_id, operator_id, env.entity_id)
                or _known(
                    db, Location.pestpac_location_id, Location.operator_id, operator_id,
                    _int(body.get("LocationID")),
                )
                or _known(
                    db, ServiceOrder.pestpac_order_id, ServiceOrder.operator_id, operator_id,
                    _int(body.get("OrderID")),
                )
            )  # fmt: skip
        case WebhookEntity.employee:
            # Technicians belong to the operator, not a bill-to: every employee event is kept.
            return True
    return False


def receive(
    db: Session, raw: bytes, signatures: list[str], timestamp: str | None
) -> WebhookEvent | None:
    """Store a delivery if it matches the bill-to rule. Returns the stored event, or None when
    it was dropped or is a redelivery. Commits."""
    env = parse_envelope(raw)
    operator = db.scalar(
        select(Tenant).where(
            Tenant.kind == TenantKind.operator, Tenant.pestpac_tenant_id == env.tenant_id
        )
    )
    if operator is None or not operator.is_active:
        log.info("Webhook dropped: unknown or inactive PestPac tenant %s", env.tenant_id)
        return None
    if env.entity is None or env.action not in SUPPORTED_ACTIONS[env.entity]:
        log.info("Webhook dropped: %s %s is not captured", env.entity_type, env.action)
        return None
    if not _matches_bill_to_rule(db, operator.id, env):
        log.debug("Webhook dropped: %s %s outside onboarded bill-tos", env.entity, env.entity_id)
        return None

    conn = db.get(PestPacConnection, operator.id)
    secret = decrypt(conn.webhook_secret_enc) if conn and conn.webhook_secret_enc else None
    signature_status = check_signature(secret, env.body, signatures, timestamp)
    if signature_status is not SignatureStatus.valid:
        log.warning(
            "Webhook signature %s for operator %s (%s %s); stored anyway (report mode)",
            signature_status, operator.id, env.entity, env.entity_id,
        )  # fmt: skip

    body = env.body or {}
    event_id = db.scalar(
        insert(WebhookEvent)
        .values(
            id=uuid.uuid4(),
            operator_id=operator.id,
            entity=env.entity,
            action=env.action,
            pestpac_entity_id=env.entity_id,
            pestpac_bill_to_id=(
                env.entity_id if env.entity is WebhookEntity.bill_to else _int(body.get("BillToID"))
            ),
            pestpac_location_id=(
                env.entity_id
                if env.entity is WebhookEntity.location
                else _int(body.get("LocationID"))
            ),
            pestpac_timestamp=timestamp[:40] if timestamp else None,
            signature_status=signature_status,
            body_sha256=hashlib.sha256(raw).hexdigest(),
            raw_body=raw.decode(),
        )
        .on_conflict_do_nothing()
        .returning(WebhookEvent.id)
    )
    db.commit()
    if event_id is None:
        log.info("Webhook redelivery ignored: %s %s", env.entity, env.entity_id)
        return None
    return db.get(WebhookEvent, event_id)


def purge_raw_bodies(db: Session, now: datetime | None = None) -> int:
    """Clear raw bodies older than the retention window. Commits; returns how many."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=get_settings().webhook_raw_retention_days)
    result = db.execute(
        update(WebhookEvent)
        .where(WebhookEvent.received_at < cutoff, WebhookEvent.raw_body.is_not(None))
        .values(raw_body=None, raw_body_purged_at=now)
    )
    db.commit()
    return result.rowcount
