"""Members: users granted a role on a tenant (staff, `memberships`) or on a company (a
customer's users, `company_memberships`). Both follow the same rules: a new user gets a
temporary password, and nobody may grant permissions they don't hold there themselves."""

import uuid
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, CompanyMembership, Membership, Role, Tenant, TenantKind, User
from app.security.access import AccessScope
from app.security.permissions import RoleScope, SystemRole
from app.services.auth import create_user, get_user_by_email
from app.services.rbac import get_system_role
from app.services.tenancy import ConflictError


class InvalidMemberRequest(Exception):
    pass


class EscalationError(Exception):
    pass


def _resolve_role(db: Session, role_name: str, expected: RoleScope, where: str) -> Role:
    role = get_system_role(db, role_name)
    if role is None:
        raise InvalidMemberRequest(f"Unknown role {role_name!r}")
    if role.scope != expected:
        raise InvalidMemberRequest(f"Role {role_name!r} cannot be assigned on {where}")
    return role


def _tenant_role(db: Session, tenant: Tenant, role_name: str) -> Role:
    expected = RoleScope.platform if tenant.kind == TenantKind.platform else RoleScope.operator
    return _resolve_role(db, role_name, expected, f"a {tenant.kind} tenant")


def _company_role(db: Session, role_name: str) -> Role:
    return _resolve_role(db, role_name, RoleScope.company, "a company")


def _check_no_escalation(held: frozenset[str], role: Role) -> None:
    """Nobody may grant permissions they don't hold there themselves."""
    missing = {p.code for p in role.permissions} - held
    if missing:
        raise EscalationError(f"Cannot grant permissions you don't hold: {sorted(missing)}")


def _held_on_company(scope: AccessScope, company: Company) -> frozenset[str]:
    return scope.permissions_on(company.operator_id, company.id)


def _user_for_new_member(
    db: Session,
    email: str,
    temporary_password: str | None,
    is_member: Callable[[uuid.UUID], bool],
) -> tuple[User, bool]:
    """The existing user with this email (unless already a member), or a new one."""
    user = get_user_by_email(db, email)
    if user is None:
        if temporary_password is None:
            raise InvalidMemberRequest("temporary_password is required for a new user")
        user = create_user(db, email=email, password=temporary_password, must_change_password=True)
        return user, True
    if is_member(user.id):
        raise ConflictError(f"{user.email} is already a member")
    return user, False


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
    role = _tenant_role(db, tenant, role_name)
    _check_no_escalation(scope.permissions_on(tenant.id), role)
    user, created = _user_for_new_member(
        db, email, temporary_password, lambda uid: get_membership(db, tenant, uid) is not None
    )

    membership = Membership(user_id=user.id, tenant_id=tenant.id, role_id=role.id)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership, user, created


def change_role(
    db: Session, scope: AccessScope, tenant: Tenant, membership: Membership, role_name: str
) -> Membership:
    role = _tenant_role(db, tenant, role_name)
    held = scope.permissions_on(tenant.id)
    _check_no_escalation(held, role)
    # Also covers the role being taken away, so a lesser admin can't demote a greater one.
    _check_no_escalation(held, membership.role)
    if role.id != membership.role_id:
        _check_not_last_platform_admin(db, membership, tenant)
    membership.role_id = role.id
    db.commit()
    db.refresh(membership)
    return membership


def remove_member(db: Session, scope: AccessScope, tenant: Tenant, membership: Membership) -> None:
    _check_no_escalation(scope.permissions_on(tenant.id), membership.role)
    _check_not_last_platform_admin(db, membership, tenant)
    db.delete(membership)
    db.commit()


def list_company_members(db: Session, company: Company) -> list[tuple[CompanyMembership, User]]:
    rows = db.execute(
        select(CompanyMembership, User)
        .join(User, User.id == CompanyMembership.user_id)
        .where(CompanyMembership.company_id == company.id)
        .options(selectinload(CompanyMembership.role), selectinload(User.credential))
        .order_by(User.email)
    ).all()
    return [(membership, user) for membership, user in rows]


def get_company_membership(
    db: Session, company: Company, user_id: uuid.UUID
) -> CompanyMembership | None:
    return db.scalar(
        select(CompanyMembership)
        .where(CompanyMembership.company_id == company.id, CompanyMembership.user_id == user_id)
        .options(selectinload(CompanyMembership.role).selectinload(Role.permissions))
    )


def add_company_member(
    db: Session,
    scope: AccessScope,
    company: Company,
    *,
    email: str,
    role_name: str,
    temporary_password: str | None,
) -> tuple[CompanyMembership, User, bool]:
    role = _company_role(db, role_name)
    _check_no_escalation(_held_on_company(scope, company), role)
    user, created = _user_for_new_member(
        db,
        email,
        temporary_password,
        lambda uid: get_company_membership(db, company, uid) is not None,
    )
    membership = CompanyMembership(user_id=user.id, company_id=company.id, role_id=role.id)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership, user, created


def change_company_role(
    db: Session,
    scope: AccessScope,
    company: Company,
    membership: CompanyMembership,
    role_name: str,
) -> CompanyMembership:
    role = _company_role(db, role_name)
    held = _held_on_company(scope, company)
    _check_no_escalation(held, role)
    _check_no_escalation(held, membership.role)
    membership.role_id = role.id
    db.commit()
    db.refresh(membership)
    return membership


def remove_company_member(
    db: Session, scope: AccessScope, company: Company, membership: CompanyMembership
) -> None:
    _check_no_escalation(_held_on_company(scope, company), membership.role)
    db.delete(membership)
    db.commit()
