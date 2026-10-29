"""Per-request access scope: which permissions the caller holds, and where.

A membership applies to its tenant and everything beneath it. The tree is two levels deep
(platform → operators), so a platform membership grants its permissions on every operator.
If a level is added (e.g. branches), extend `permissions_on` to walk the ancestor chain.

Company grants (customer users, `company_memberships`) apply to that one company only, and
only where a route passes `company_id`: every other route checks the operator, so a company
user can't see anything a route hasn't been opened to.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Company, CompanyMembership, Membership, Role, Tenant, TenantKind, User
from app.security.deps import get_active_user
from app.security.permissions import Perm


@dataclass(frozen=True)
class AccessScope:
    user_id: uuid.UUID
    platform_id: uuid.UUID | None
    # Permissions granted on the platform tenant apply everywhere.
    global_perms: frozenset[str] = frozenset()
    operator_perms: dict[uuid.UUID, frozenset[str]] = field(default_factory=dict)
    company_perms: dict[uuid.UUID, frozenset[str]] = field(default_factory=dict)

    def permissions_on(
        self, tenant_id: uuid.UUID, company_id: uuid.UUID | None = None
    ) -> frozenset[str]:
        """Permissions on a tenant; with `company_id` (a company of that operator), also the
        caller's grant on that company."""
        if tenant_id == self.platform_id:
            return self.global_perms
        perms = self.global_perms | self.operator_perms.get(tenant_id, frozenset())
        if company_id is not None:
            perms |= self.company_perms.get(company_id, frozenset())
        return perms

    def can(self, perm: Perm, tenant_id: uuid.UUID, company_id: uuid.UUID | None = None) -> bool:
        return perm.value in self.permissions_on(tenant_id, company_id)

    def has_anywhere(self, perm: Perm) -> bool:
        return perm.value in self.global_perms or any(
            perm.value in perms for perms in self.operator_perms.values()
        )

    def operator_ids_with(self, perm: Perm) -> set[uuid.UUID] | None:
        """Operator ids where `perm` is held; None means every operator."""
        if perm.value in self.global_perms:
            return None
        return {op_id for op_id, perms in self.operator_perms.items() if perm.value in perms}

    def require(
        self,
        perm: Perm,
        tenant_id: uuid.UUID,
        *,
        read_perm: Perm,
        company_id: uuid.UUID | None = None,
    ) -> None:
        """404 when the caller can't see the resource at all, 403 when they can see it but
        lack `perm`. Hiding existence keeps one operator from probing another's records.
        Pass `company_id` only on routes company users may use (see the module docstring)."""
        if not self.can(read_perm, tenant_id, company_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        if not self.can(perm, tenant_id, company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission {perm.value}"
            )


def load_scope(db: Session, user_id: uuid.UUID) -> AccessScope:
    rows: Iterable[tuple[Membership, TenantKind]] = db.execute(
        select(Membership, Tenant.kind)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(Membership.user_id == user_id, Tenant.is_active.is_(True))
        .options(selectinload(Membership.role).selectinload(Role.permissions))
    ).all()
    platform_id = db.scalar(select(Tenant.id).where(Tenant.kind == TenantKind.platform))
    global_perms: set[str] = set()
    operator_perms: dict[uuid.UUID, frozenset[str]] = {}
    for membership, kind in rows:
        codes = frozenset(p.code for p in membership.role.permissions)
        if kind == TenantKind.platform:
            global_perms |= codes
        else:
            operator_perms[membership.tenant_id] = codes
    company_grants = db.scalars(
        select(CompanyMembership)
        .join(Company, Company.id == CompanyMembership.company_id)
        .join(Tenant, Tenant.id == Company.operator_id)
        .where(
            CompanyMembership.user_id == user_id,
            Company.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
        .options(selectinload(CompanyMembership.role).selectinload(Role.permissions))
    )
    company_perms = {
        grant.company_id: frozenset(p.code for p in grant.role.permissions)
        for grant in company_grants
    }
    return AccessScope(
        user_id=user_id,
        platform_id=platform_id,
        global_perms=frozenset(global_perms),
        operator_perms=operator_perms,
        company_perms=company_perms,
    )


def get_scope(user: User = Depends(get_active_user), db: Session = Depends(get_db)) -> AccessScope:
    return load_scope(db, user.id)


def require_any(perm: Perm):
    """Route-level gate for endpoints not tied to one tenant (e.g. listing roles)."""

    def dependency(scope: AccessScope = Depends(get_scope)) -> AccessScope:
        if not scope.has_anywhere(perm):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing permission {perm.value}"
            )
        return scope

    return dependency
