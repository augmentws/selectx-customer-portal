import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.tenancy import Crumb


class RiskInspectionListItem(BaseModel):
    """One risk inspection in a company's or location's list."""

    id: uuid.UUID
    gocanvas_submission_id: int
    submission_number: str | None
    # The form's date and time: the store's wall-clock time.
    inspected_at: datetime | None
    inspector_name: str | None
    store_label: str | None
    location_id: uuid.UUID | None
    location_name: str | None
    work_order_ref: str | None
    service_order_id: uuid.UUID | None
    ramp_recommendation: int | None
    # The highest overall zone risk (1-5) among inspected zones.
    highest_risk: int | None
    zones_inspected: int
    zones_with_activity: int
    is_revision: bool
    revised_at: datetime | None


class RiskInspectionPhoto(BaseModel):
    """A photo, opened through GET /v1/files/{file_id}."""

    file_id: uuid.UUID
    # pest, sanitation, structural, or additional.
    category: str | None
    position: int
    file_name: str


class RiskInspectionZoneRead(BaseModel):
    zone_key: str
    name: str
    position: int
    inspected: str | None
    has_activity: bool
    all_areas_inspected: bool | None
    areas: list[str]
    doors_are: list[str]
    door_sweeps_ok: bool | None
    doors_aligned: bool | None
    rodent_activity: bool | None
    pest_activity: bool | None
    pest_types: list[str]
    additional_notes: str | None
    pest_notes: str | None
    sanitation_notes: str | None
    structural_notes: str | None
    sanitation_risk: int | None
    structural_risk: int | None
    overall_risk: int | None
    # Zone-specific answers: dumpster, trash_room, basement, ceiling, exterior_perimeter,
    # paneling (lists), in_mall, dumbwaiter_operational (booleans), mall (list).
    attributes: dict[str, list[str] | bool]
    photos: list[RiskInspectionPhoto]


class RiskInspectionMaterialRead(BaseModel):
    material_key: str
    name: str
    used: bool | None
    quantity: Decimal | None


class RiskInspectionDetail(RiskInspectionListItem):
    """A risk inspection with everything its report shows."""

    trail: list[Crumb]
    address: str | None
    city: str | None
    manager_summary: str | None
    material_notes: str | None
    zones: list[RiskInspectionZoneRead]
    materials: list[RiskInspectionMaterialRead]
    # Photo fields whose images haven't been fetched from GoCanvas yet (or failed).
    photos_pending: int
    parse_warning_count: int
