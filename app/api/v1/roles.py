from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import Permission, Role
from app.schemas.tenancy import PermissionRead, RoleRead
from app.security.access import require_any
from app.security.permissions import Perm

router = APIRouter(tags=["roles"])


@router.get(
    "/roles", response_model=list[RoleRead], dependencies=[Depends(require_any(Perm.roles_read))]
)
def list_roles(db: Session = Depends(get_db)):
    roles = db.scalars(
        select(Role)
        .where(Role.tenant_id.is_(None))
        .options(selectinload(Role.permissions))
        .order_by(Role.scope, Role.name)
    )
    return [
        RoleRead(
            name=r.name,
            description=r.description,
            scope=r.scope,
            permissions=sorted(p.code for p in r.permissions),
        )
        for r in roles
    ]


@router.get(
    "/permissions",
    response_model=list[PermissionRead],
    dependencies=[Depends(require_any(Perm.roles_read))],
)
def list_permissions(db: Session = Depends(get_db)):
    return list(db.scalars(select(Permission).order_by(Permission.code)))
