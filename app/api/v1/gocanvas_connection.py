import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import GoCanvasConnection, Tenant
from app.schemas.gocanvas import GoCanvasConnectionRead, GoCanvasConnectionWrite
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import gocanvas_connection as service
from app.services import tenancy

router = APIRouter(prefix="/operators/{operator_id}/gocanvas-connection", tags=["gocanvas"])


def _operator(db: Session, scope: AccessScope, operator_id: uuid.UUID, perm: Perm) -> Tenant:
    operator = tenancy.get_operator(db, operator_id)
    if operator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(perm, operator.id, read_perm=Perm.operators_read)
    return operator


def _read(operator: Tenant, conn: GoCanvasConnection | None) -> GoCanvasConnectionRead:
    if conn is None:
        return GoCanvasConnectionRead(operator_id=operator.id, configured=False)
    return GoCanvasConnectionRead(
        operator_id=operator.id,
        configured=True,
        client_id=conn.client_id,
        has_client_secret=bool(conn.client_secret_enc),
        status=conn.status,
        last_verified_at=conn.last_verified_at,
        last_error=conn.last_error,
        updated_at=conn.updated_at,
    )


@router.get("", response_model=GoCanvasConnectionRead)
def get_connection(
    operator_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    operator = _operator(db, scope, operator_id, Perm.gocanvas_connection_read)
    return _read(operator, service.get_connection(db, operator.id))


@router.put("", response_model=GoCanvasConnectionRead)
def save_connection(
    operator_id: uuid.UUID,
    data: GoCanvasConnectionWrite,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Save credentials, then test them against GoCanvas. The response carries the result."""
    operator = _operator(db, scope, operator_id, Perm.gocanvas_connection_write)
    try:
        conn = service.save_connection(db, operator, data, scope.user_id)
    except service.MissingSecretError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None
    return _read(operator, service.verify_connection(db, operator, conn))


@router.post("/verify", response_model=GoCanvasConnectionRead)
def verify_connection(
    operator_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    operator = _operator(db, scope, operator_id, Perm.gocanvas_connection_write)
    conn = service.get_connection(db, operator.id)
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="GoCanvas API access is not set up"
        )
    return _read(operator, service.verify_connection(db, operator, conn))
