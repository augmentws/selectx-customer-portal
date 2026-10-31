import uuid

from pydantic import BaseModel, Field

from app.models import Zone


class ZoneRead(BaseModel):
    """A zone with the operator's display name for it."""

    zone: Zone
    display_name: str
    default_name: str


class ZoneUpdate(BaseModel):
    # Empty or null restores the default name.
    display_name: str | None = Field(default=None, max_length=100)


class AreaTypeRead(BaseModel):
    """A PestPac area type and the zone its areas count as."""

    id: uuid.UUID
    pestpac_area_type_id: int
    code: str
    description: str | None
    zone: Zone | None  # null: not mapped
    zone_name: str | None
    # Current location areas of this type.
    areas: int


class AreaTypeUpdate(BaseModel):
    zone: Zone | None


class AreaTypeSyncRead(BaseModel):
    total: int
    added: int
    updated: int
    removed: int
