import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Membership, Tenant, User
from app.schemas.tenancy import MemberCreate, MemberCreated, MemberRead, MemberUpdate
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import members as members_service
from app.services.tenancy import ConflictError

router = APIRouter(prefix="/tenants/{tenant_id}/members", tags=["members"])


def _tenant_for(db: Session, scope: AccessScope, tenant_id: uuid.UUID, perm: Perm) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(perm, tenant.id, read_perm=Perm.operators_read)
    return tenant


def _read(membership: Membership, user: User) -> MemberRead:
    return MemberRead(
        user_id=user.id,
        email=user.email,
        tenant_id=membership.tenant_id,
        role=membership.role.name,
        must_change_password=bool(user.credential and user.credential.must_change_password),
        created_at=membership.created_at,
    )


def _membership_or_404(db: Session, tenant: Tenant, user_id: uuid.UUID) -> Membership:
    membership = members_service.get_membership(db, tenant, user_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return membership


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, members_service.EscalationError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


_DOMAIN_ERRORS = (
    members_service.InvalidMemberRequest,
    members_service.EscalationError,
    ConflictError,
)


@router.get("", response_model=list[MemberRead])
def list_members(
    tenant_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    tenant = _tenant_for(db, scope, tenant_id, Perm.members_read)
    return [_read(m, u) for m, u in members_service.list_members(db, tenant)]


@router.post("", response_model=MemberCreated, status_code=status.HTTP_201_CREATED)
def add_member(
    tenant_id: uuid.UUID,
    data: MemberCreate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    tenant = _tenant_for(db, scope, tenant_id, Perm.members_write)
    try:
        membership, user, created = members_service.add_member(
            db,
            scope,
            tenant,
            email=data.email,
            role_name=data.role,
            temporary_password=data.temporary_password,
        )
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc) from None
    return MemberCreated(**_read(membership, user).model_dump(), user_created=created)


@router.patch("/{user_id}", response_model=MemberRead)
def change_role(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    data: MemberUpdate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    tenant = _tenant_for(db, scope, tenant_id, Perm.members_write)
    membership = _membership_or_404(db, tenant, user_id)
    try:
        membership = members_service.change_role(db, scope, tenant, membership, data.role)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc) from None
    return _read(membership, db.get(User, user_id))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    tenant = _tenant_for(db, scope, tenant_id, Perm.members_write)
    membership = _membership_or_404(db, tenant, user_id)
    try:
        members_service.remove_member(db, scope, tenant, membership)
    except _DOMAIN_ERRORS as exc:
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
