from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Permission, Role, Tenant, TenantKind
from app.security.permissions import PERMISSION_DESCRIPTIONS, SYSTEM_ROLES, Perm, SystemRole

PLATFORM_SLUG = "selectx"


def sync_rbac(db: Session) -> list[str]:
    """Make the permissions table and system roles match app.security.permissions.

    Returns a description of each change made (empty when already in sync). Does not commit.
    """
    changes: list[str] = []
    existing = {p.code: p for p in db.scalars(select(Permission))}
    for perm in Perm:
        desc = PERMISSION_DESCRIPTIONS[perm]
        row = existing.pop(perm.value, None)
        if row is None:
            db.add(Permission(code=perm.value, description=desc))
            changes.append(f"add permission {perm.value}")
        elif row.description != desc:
            row.description = desc
            changes.append(f"update permission {perm.value}")
    for stale in existing.values():
        db.delete(stale)
        changes.append(f"remove permission {stale.code}")
    db.flush()

    perms_by_code = {p.code: p for p in db.scalars(select(Permission))}
    roles = {
        r.name: r
        for r in db.scalars(
            select(Role).where(Role.tenant_id.is_(None)).options(selectinload(Role.permissions))
        )
    }
    for name, (scope, desc, codes) in SYSTEM_ROLES.items():
        role = roles.get(name.value)
        if role is None:
            role = Role(name=name.value, description=desc, scope=scope, permissions=[])
            db.add(role)
            changes.append(f"add role {name.value}")
        if role.description != desc or role.scope != scope:
            role.description, role.scope = desc, scope
            changes.append(f"update role {name.value}")
        wanted = {c.value for c in codes}
        if {p.code for p in role.permissions} != wanted:
            role.permissions = [perms_by_code[c] for c in sorted(wanted)]
            changes.append(f"update permissions of role {name.value}")
    db.flush()
    return changes


def get_platform_tenant(db: Session) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.kind == TenantKind.platform))
    if tenant is None:
        raise RuntimeError("Platform tenant missing; run `alembic upgrade head`")
    return tenant


def get_system_role(db: Session, name: SystemRole | str) -> Role | None:
    return db.scalar(
        select(Role)
        .where(Role.tenant_id.is_(None), Role.name == str(name))
        .options(selectinload(Role.permissions))
    )
