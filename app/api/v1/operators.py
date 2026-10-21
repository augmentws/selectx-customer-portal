import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Tenant
from app.schemas.tenancy import (
    CompanyCreate,
    CompanyRead,
    OperatorCreate,
    OperatorRead,
    OperatorUpdate,
)
from app.security.access import AccessScope, get_scope, require_any
from app.security.permissions import Perm
from app.services import tenancy

router = APIRouter(prefix="/operators", tags=["operators"])


def _operator_or_404(db: Session, operator_id: uuid.UUID) -> Tenant:
    operator = tenancy.get_operator(db, operator_id)
    if operator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return operator


@router.get("", response_model=list[OperatorRead])
def list_operators(
    db: Session = Depends(get_db), scope: AccessScope = Depends(require_any(Perm.operators_read))
):
    return tenancy.list_operators(db, scope.operator_ids_with(Perm.operators_read))


@router.post("", response_model=OperatorRead, status_code=status.HTTP_201_CREATED)
def create_operator(
    data: OperatorCreate, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    # Creating operators is a platform-level action.
    if scope.platform_id is None or not scope.can(Perm.operators_write, scope.platform_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission {Perm.operators_write.value}",
        )
    try:
        return tenancy.create_operator(db, data)
    except tenancy.ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None


@router.get("/{operator_id}", response_model=OperatorRead)
def get_operator(
    operator_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    operator = _operator_or_404(db, operator_id)
    scope.require(Perm.operators_read, operator.id, read_perm=Perm.operators_read)
    return operator


@router.patch("/{operator_id}", response_model=OperatorRead)
def update_operator(
    operator_id: uuid.UUID,
    data: OperatorUpdate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    operator = _operator_or_404(db, operator_id)
    scope.require(Perm.operators_write, operator.id, read_perm=Perm.operators_read)
    try:
        return tenancy.update_operator(db, operator, data)
    except tenancy.ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None


@router.get("/{operator_id}/companies", response_model=list[CompanyRead])
def list_companies(
    operator_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    operator = _operator_or_404(db, operator_id)
    scope.require(Perm.companies_read, operator.id, read_perm=Perm.operators_read)
    return tenancy.list_companies(db, operator.id)


@router.post(
    "/{operator_id}/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED
)
def create_company(
    operator_id: uuid.UUID,
    data: CompanyCreate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    operator = _operator_or_404(db, operator_id)
    scope.require(Perm.companies_write, operator.id, read_perm=Perm.operators_read)
    return tenancy.create_company(db, operator, data)
