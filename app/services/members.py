import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Membership, Role, Tenant, TenantKind, User
from app.security.access import AccessScope
from app.security.permissions import RoleScope, SystemRole
from app.services.auth import create_user, get_user_by_email
from app.services.rbac import get_system_role
from app.services.tenancy import ConflictError


class InvalidMemberRequest(Exception):
    pass


class EscalationError(Exception):
    pass


def _resolve_role(db: Session, tenant: Tenant, role_name: str) -> Role:
    role = get_system_role(db, role_name)
    if role is None:
        raise InvalidMemberRequest(f"Unknown role {role_name!r}")
    expected = RoleScope.platform if tenant.kind == TenantKind.platform else RoleScope.operator
    if role.scope != expected:
        raise InvalidMemberRequest(
            f"Role {role_name!r} cannot be assigned on a {tenant.kind} tenant"
        )
    return role


def _check_no_escalation(scope: AccessScope, tenant: Tenant, role: Role) -> None:
    """Nobody may grant permissions they don't hold on that tenant themselves."""
    missing = {p.code for p in role.permissions} - scope.permissions_on(tenant.id)
    if missing:
        raise EscalationError(f"Cannot grant permissions you don't hold: {sorted(missing)}")


def _check_not_last_platform_admin(db: Session, membership: Membership, tenant: Tenant) -> None:
    if tenant.kind != TenantKind.platform or membership.role.name != SystemRole.platform_admin:
        return
    count = db.scalar(
        select(func.count())
        .select_from(Membership)
        .join(Role, Role.id == Membership.role_id)
        .where(Membership.tenant_id == tenant.id, Role.name == SystemRole.platform_admin.value)
    )
    if count <= 1:
        raise ConflictError("Cannot remove or demote the last platform admin")


def list_members(db: Session, tenant: Tenant) -> list[tuple[Membership, User]]:
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == tenant.id)
        .options(selectinload(Membership.role), selectinload(User.credential))
        .order_by(User.email)
    ).all()
    return [(membership, user) for membership, user in rows]


def get_membership(db: Session, tenant: Tenant, user_id: uuid.UUID) -> Membership | None:
    return db.scalar(
        select(Membership)
        .where(Membership.tenant_id == tenant.id, Membership.user_id == user_id)
        .options(selectinload(Membership.role).selectinload(Role.permissions))
    )


def add_member(
    db: Session,
    scope: AccessScope,
    tenant: Tenant,
    *,
    email: str,
    role_name: str,
    temporary_password: str | None,
) -> tuple[Membership, User, bool]:
    role = _resolve_role(db, tenant, role_name)
    _check_no_escalation(scope, tenant, role)

    user = get_user_by_email(db, email)
    created = user is None
    if user is None:
        if temporary_password is None:
            raise InvalidMemberRequest("temporary_password is required for a new user")
        user = create_user(db, email=email, password=temporary_password, must_change_password=True)
    elif get_membership(db, tenant, user.id) is not None:
        raise ConflictError(f"{user.email} is already a member")

    membership = Membership(user_id=user.id, tenant_id=tenant.id, role_id=role.id)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership, user, created


def change_role(
    db: Session, scope: AccessScope, tenant: Tenant, membership: Membership, role_name: str
) -> Membership:
    role = _resolve_role(db, tenant, role_name)
    _check_no_escalation(scope, tenant, role)
    # Also covers the role being taken away, so a lesser admin can't demote a greater one.
    _check_no_escalation(scope, tenant, membership.role)
    if role.id != membership.role_id:
        _check_not_last_platform_admin(db, membership, tenant)
    membership.role_id = role.id
    db.commit()
    db.refresh(membership)
    return membership


def remove_member(db: Session, scope: AccessScope, tenant: Tenant, membership: Membership) -> None:
    _check_no_escalation(scope, tenant, membership.role)
    _check_not_last_platform_admin(db, membership, tenant)
    db.delete(membership)
    db.commit()
