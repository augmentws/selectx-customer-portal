"""Per-operator PestPac API access: storing credentials, verifying them, and building clients."""

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.pestpac import (
    CredentialManager,
    PestPacAuthError,
    PestPacClient,
    PestPacCredentials,
)
from app.models import ConnectionStatus, PestPacConnection, Tenant
from app.schemas.pestpac import PestPacBillToDetails, PestPacConnectionWrite
from app.security.secrets import SecretDecryptionError, decrypt, encrypt
from app.services.errors import ConflictError

log = logging.getLogger(__name__)


class MissingSecretError(Exception):
    pass


class ConnectionNotReadyError(Exception):
    pass


class PestPacUnavailableError(Exception):
    pass


def get_connection(db: Session, operator_id: uuid.UUID) -> PestPacConnection | None:
    return db.get(PestPacConnection, operator_id)


def save_connection(
    db: Session, operator: Tenant, data: PestPacConnectionWrite, user_id: uuid.UUID
) -> PestPacConnection:
    """Store credentials (secrets encrypted) and mark the connection unverified.

    Omitted secrets keep their stored value; all three are required on first save.
    """
    if not operator.pestpac_tenant_id:
        raise ConflictError("This operator has no PestPac tenant ID; a platform admin must set it")
    conn = get_connection(db, operator.id)
    if conn is None:
        missing = [
            name for name in ("client_secret", "password", "api_key") if getattr(data, name) is None
        ]
        if missing:
            raise MissingSecretError(f"Required for the first setup: {', '.join(missing)}")
        conn = PestPacConnection(operator_id=operator.id)
        db.add(conn)

    conn.base_url = get_settings().pestpac_default_base_url
    conn.client_id = data.client_id
    conn.username = data.username
    if data.client_secret is not None:
        conn.client_secret_enc = encrypt(data.client_secret)
    if data.password is not None:
        conn.password_enc = encrypt(data.password)
    if data.api_key is not None:
        conn.api_key_enc = encrypt(data.api_key)
        conn.api_key_last4 = data.api_key[-4:]
    mark_unverified(conn)
    conn.updated_by = user_id
    db.commit()
    _forget_client(operator.id)
    return conn


def mark_unverified(conn: PestPacConnection) -> None:
    conn.status = ConnectionStatus.unverified
    conn.last_error = None
    conn.pestpac_company_id = None
    conn.pestpac_company_name = None


def _build_client(conn: PestPacConnection, tenant_id: str) -> PestPacClient:
    settings = get_settings()
    credentials = PestPacCredentials(
        tenant_id=tenant_id,
        api_key=decrypt(conn.api_key_enc),
        client_id=conn.client_id,
        client_secret=decrypt(conn.client_secret_enc),
        username=conn.username,
        password=decrypt(conn.password_enc),
    )
    return PestPacClient(
        CredentialManager(credentials, token_url=settings.pestpac_token_url),
        base_url=conn.base_url,
        debug_bodies=settings.pestpac_debug_bodies,
    )


def verify_connection(db: Session, operator: Tenant, conn: PestPacConnection) -> PestPacConnection:
    """Fetch a token, then GET /CompanySetup with the API key and tenant ID. Records the result."""
    conn.last_verified_at = datetime.now(UTC)
    try:
        client = _build_client(conn, operator.pestpac_tenant_id)
        response = client.company_setup()
    except SecretDecryptionError:
        _fail(conn, "Stored credentials can't be decrypted; re-enter the secrets")
    except PestPacAuthError as exc:
        _fail(conn, str(exc))
    except requests.RequestException as exc:
        _fail(conn, f"Could not reach PestPac: {type(exc).__name__}")
    else:
        if response.status_code in (401, 403):
            _fail(
                conn,
                f"PestPac refused /CompanySetup ({response.status_code}); "
                "check the API key and tenant ID",
            )
        elif response.status_code != 200:
            _fail(conn, f"PestPac /CompanySetup returned {response.status_code}")
        else:
            _succeed(conn, _json_or_none(response))
    db.commit()
    _forget_client(operator.id)
    return conn


def _json_or_none(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _fail(conn: PestPacConnection, message: str) -> None:
    conn.status = ConnectionStatus.failed
    conn.last_error = message[:500]
    conn.pestpac_company_id = None
    conn.pestpac_company_name = None


def _succeed(conn: PestPacConnection, body: Any) -> None:
    if not isinstance(body, dict) or "CompanyID" not in body:
        _fail(conn, "PestPac /CompanySetup returned an unexpected response")
        return
    conn.status = ConnectionStatus.verified
    conn.last_error = None
    conn.pestpac_company_id = body.get("CompanyID")
    conn.pestpac_company_name = (body.get("Company") or "")[:255] or None


# Clients are cached per operator so their access tokens are reused across requests. Saving or
# verifying a connection drops the cached client, so new credentials take effect immediately.
_clients: dict[uuid.UUID, PestPacClient] = {}
_clients_lock = threading.Lock()


def _forget_client(operator_id: uuid.UUID) -> None:
    with _clients_lock:
        _clients.pop(operator_id, None)


def get_pestpac_client(db: Session, operator: Tenant) -> PestPacClient:
    """A client for an operator whose connection is verified."""
    conn = get_connection(db, operator.id)
    if conn is None or conn.status != ConnectionStatus.verified:
        raise ConnectionNotReadyError("Set up and verify PestPac API access first")
    with _clients_lock:
        client = _clients.get(operator.id)
        if client is None:
            try:
                client = _build_client(conn, operator.pestpac_tenant_id)
            except SecretDecryptionError as exc:
                raise ConnectionNotReadyError(
                    "Stored PestPac credentials can't be decrypted; re-enter them"
                ) from exc
            _clients[operator.id] = client
        return client


def fetch_bill_to(client: PestPacClient, pestpac_bill_to_id: int) -> PestPacBillToDetails | None:
    """Identifying details for a bill-to, or None if PestPac has no such BillToID."""
    try:
        response = client.bill_tos.get(pestpac_bill_to_id)
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise PestPacUnavailableError(f"PestPac /BillTos returned {response.status_code}")
    body = _json_or_none(response)
    if not isinstance(body, dict) or body.get("BillToID") != pestpac_bill_to_id:
        raise PestPacUnavailableError("PestPac /BillTos returned an unexpected response")
    return PestPacBillToDetails.from_api(body)
