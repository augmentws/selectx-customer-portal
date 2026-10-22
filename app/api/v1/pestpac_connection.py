import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import PestPacConnection, Tenant
from app.schemas.pestpac import PestPacConnectionRead, PestPacConnectionWrite
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import pestpac_connection as service
from app.services import tenancy
from app.services.errors import ConflictError

router = APIRouter(prefix="/operators/{operator_id}/pestpac-connection", tags=["pestpac"])


def _operator(db: Session, scope: AccessScope, operator_id: uuid.UUID, perm: Perm) -> Tenant:
    operator = tenancy.get_operator(db, operator_id)
    if operator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(perm, operator.id, read_perm=Perm.operators_read)
    return operator


def _read(operator: Tenant, conn: PestPacConnection | None) -> PestPacConnectionRead:
    base = {"operator_id": operator.id, "pestpac_tenant_id": operator.pestpac_tenant_id}
    if conn is None:
        return PestPacConnectionRead(**base, configured=False)
    return PestPacConnectionRead(
        **base,
        configured=True,
        base_url=conn.base_url,
        client_id=conn.client_id,
        username=conn.username,
        has_client_secret=bool(conn.client_secret_enc),
        has_password=bool(conn.password_enc),
        api_key_last4=conn.api_key_last4,
        has_webhook_secret=bool(conn.webhook_secret_enc),
        status=conn.status,
        last_verified_at=conn.last_verified_at,
        last_error=conn.last_error,
        pestpac_company_id=conn.pestpac_company_id,
        pestpac_company_name=conn.pestpac_company_name,
        updated_at=conn.updated_at,
    )


@router.get("", response_model=PestPacConnectionRead)
def get_connection(
    operator_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    operator = _operator(db, scope, operator_id, Perm.pestpac_connection_read)
    return _read(operator, service.get_connection(db, operator.id))


@router.put("", response_model=PestPacConnectionRead)
def save_connection(
    operator_id: uuid.UUID,
    data: PestPacConnectionWrite,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Save credentials, then test them against PestPac. The response carries the result."""
    operator = _operator(db, scope, operator_id, Perm.pestpac_connection_write)
    try:
        conn = service.save_connection(db, operator, data, scope.user_id)
    except service.MissingSecretError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return _read(operator, service.verify_connection(db, operator, conn))


@router.post("/verify", response_model=PestPacConnectionRead)
def verify_connection(
    operator_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    operator = _operator(db, scope, operator_id, Perm.pestpac_connection_write)
    conn = service.get_connection(db, operator.id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="PestPac API access is not set up"
        )
    return _read(operator, service.verify_connection(db, operator, conn))
