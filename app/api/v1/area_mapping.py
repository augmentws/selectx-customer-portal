import dataclasses
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.v1._pestpac_errors import pestpac_errors
from app.db.session import get_db
from app.models import DEFAULT_ZONE_NAMES, AreaType, Tenant, Zone
from app.schemas.area_mapping import (
    AreaTypeRead,
    AreaTypeSyncRead,
    AreaTypeUpdate,
    ZoneRead,
    ZoneUpdate,
)
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import area_mapping, pestpac_connection, tenancy

router = APIRouter(tags=["area mapping"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _operator(db: Session, scope: AccessScope, operator_id: uuid.UUID, perm: Perm) -> Tenant:
    operator = tenancy.get_operator(db, operator_id)
    if operator is None:
        raise _not_found()
    scope.require(perm, operator.id, read_perm=Perm.bill_tos_read)
    return operator


def _zones(db: Session, operator_id: uuid.UUID) -> list[ZoneRead]:
    names = area_mapping.zone_names(db, operator_id)
    return [
        ZoneRead(zone=z, display_name=names[z], default_name=DEFAULT_ZONE_NAMES[z]) for z in Zone
    ]


def _area_type(t: AreaType, areas: int, names: dict[Zone, str]) -> AreaTypeRead:
    return AreaTypeRead(
        id=t.id,
        pestpac_area_type_id=t.pestpac_area_type_id,
        code=t.code,
        description=t.description,
        zone=t.zone,
        zone_name=names[Zone(t.zone)] if t.zone else None,
        areas=areas,
    )


def _area_types(db: Session, operator_id: uuid.UUID) -> list[AreaTypeRead]:
    names = area_mapping.zone_names(db, operator_id)
    return [_area_type(t, n, names) for t, n in area_mapping.list_area_types(db, operator_id)]


@router.get("/operators/{operator_id}/zones", response_model=list[ZoneRead])
def list_zones(
    operator_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The fixed zones with the operator's display names, in their standard order."""
    operator = _operator(db, scope, operator_id, Perm.bill_tos_read)
    return _zones(db, operator.id)


@router.put("/operators/{operator_id}/zones/{zone}", response_model=list[ZoneRead])
def set_zone_name(
    operator_id: uuid.UUID,
    zone: Zone,
    body: ZoneUpdate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Set the operator's display name for a zone (empty restores the default); returns every
    zone."""
    operator = _operator(db, scope, operator_id, Perm.bill_tos_write)
    area_mapping.set_zone_name(db, operator.id, zone, body.display_name)
    db.commit()
    return _zones(db, operator.id)


@router.get("/operators/{operator_id}/area-types", response_model=list[AreaTypeRead])
def list_area_types(
    operator_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """PestPac's area types as last synced, by code, each with its zone and how many location
    areas use it."""
    operator = _operator(db, scope, operator_id, Perm.bill_tos_read)
    return _area_types(db, operator.id)


@router.post("/operators/{operator_id}/area-types/sync", response_model=AreaTypeSyncRead)
def sync_area_types(
    operator_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Fetch PestPac's area types now (GET /lookups/AreaTypes). New types start with a default
    zone; known types keep theirs. 409 without a verified connection, 502 if PestPac fails."""
    operator = _operator(db, scope, operator_id, Perm.bill_tos_write)
    with pestpac_errors():
        client = pestpac_connection.get_pestpac_client(db, operator)
        counts = area_mapping.sync_area_types(db, operator.id, client)
    db.commit()
    return AreaTypeSyncRead(**dataclasses.asdict(counts))


@router.patch("/area-types/{area_type_id}", response_model=AreaTypeRead)
def update_area_type(
    area_type_id: uuid.UUID,
    body: AreaTypeUpdate,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(get_scope),
):
    """Map an area type to a zone (null: unmapped)."""
    area_type = db.get(AreaType, area_type_id)
    if area_type is None:
        raise _not_found()
    scope.require(Perm.bill_tos_write, area_type.operator_id, read_perm=Perm.bill_tos_read)
    area_type.zone = body.zone.value if body.zone else None
    db.commit()
    names = area_mapping.zone_names(db, area_type.operator_id)
    return _area_type(area_type, area_mapping.areas_of_type(db, area_type), names)
