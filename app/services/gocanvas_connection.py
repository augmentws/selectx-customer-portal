"""Per-operator GoCanvas API access: storing credentials, verifying them, and building clients.

Mirrors app.services.pestpac_connection. GoCanvas's client credentials are the whole of its
authentication, so verifying means GoCanvas issues a token for them.
"""

import threading
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.gocanvas import GoCanvasAuthError, GoCanvasClient
from app.models import ConnectionStatus, GoCanvasConnection, Tenant
from app.schemas.gocanvas import GoCanvasConnectionWrite
from app.security.secrets import SecretDecryptionError, decrypt, encrypt


class MissingSecretError(Exception):
    pass


class ConnectionNotReadyError(Exception):
    pass


def get_connection(db: Session, operator_id: uuid.UUID) -> GoCanvasConnection | None:
    return db.get(GoCanvasConnection, operator_id)


def save_connection(
    db: Session, operator: Tenant, data: GoCanvasConnectionWrite, user_id: uuid.UUID
) -> GoCanvasConnection:
    """Store credentials (the secret encrypted) and mark the connection unverified.

    An omitted secret keeps its stored value; it's required on first save.
    """
    conn = get_connection(db, operator.id)
    if conn is None:
        if data.client_secret is None:
            raise MissingSecretError("Required for the first setup: client_secret")
        conn = GoCanvasConnection(operator_id=operator.id)
        db.add(conn)
    conn.client_id = data.client_id
    if data.client_secret is not None:
        conn.client_secret_enc = encrypt(data.client_secret)
    conn.status = ConnectionStatus.unverified
    conn.last_error = None
    conn.updated_by = user_id
    db.commit()
    _forget_client(operator.id)
    return conn


def _build_client(conn: GoCanvasConnection) -> GoCanvasClient:
    settings = get_settings()
    return GoCanvasClient(
        conn.client_id,
        decrypt(conn.client_secret_enc),
        token_url=settings.gocanvas_token_url,
        base_url=settings.gocanvas_base_url,
    )


def verify_connection(
    db: Session, operator: Tenant, conn: GoCanvasConnection
) -> GoCanvasConnection:
    """Ask GoCanvas for a token with the stored credentials. Records the result."""
    conn.last_verified_at = datetime.now(UTC)
    try:
        _build_client(conn).get_token(force_refresh=True)
    except SecretDecryptionError:
        _fail(conn, "Stored credentials can't be decrypted; re-enter the client secret")
    except GoCanvasAuthError as exc:
        _fail(conn, str(exc))
    else:
        conn.status = ConnectionStatus.verified
        conn.last_error = None
    db.commit()
    _forget_client(operator.id)
    return conn


def _fail(conn: GoCanvasConnection, message: str) -> None:
    conn.status = ConnectionStatus.failed
    conn.last_error = message[:500]


# Clients are cached per operator so their access tokens are reused. Saving or verifying a
# connection drops the cached client, so new credentials take effect immediately.
_clients: dict[uuid.UUID, GoCanvasClient] = {}
_clients_lock = threading.Lock()


def _forget_client(operator_id: uuid.UUID) -> None:
    with _clients_lock:
        _clients.pop(operator_id, None)


def get_gocanvas_client(db: Session, operator: Tenant) -> GoCanvasClient:
    """A client for an operator whose connection is verified."""
    conn = get_connection(db, operator.id)
    if conn is None or conn.status != ConnectionStatus.verified:
        raise ConnectionNotReadyError("Set up and verify GoCanvas API access first")
    with _clients_lock:
        client = _clients.get(operator.id)
        if client is None:
            try:
                client = _build_client(conn)
            except SecretDecryptionError as exc:
                raise ConnectionNotReadyError(
                    "Stored GoCanvas credentials can't be decrypted; re-enter them"
                ) from exc
            _clients[operator.id] = client
        return client
