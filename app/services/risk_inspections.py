"""Reading risk inspections: a company's or location's list, and one inspection's report.

Only submissions linked to a location are listed (that's how they belong to a company); an
unlinked one can still be opened by id.
"""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    BillTo,
    InspectionForm,
    InspectionKind,
    InspectionPhoto,
    InspectionPhotoValue,
    InspectionSubmission,
    Location,
)
from app.schemas.inspections import (
    RiskInspectionDetail,
    RiskInspectionListItem,
    RiskInspectionMaterialRead,
    RiskInspectionPhoto,
    RiskInspectionZoneRead,
)
from app.services import trail
from app.services.inspections import MATERIAL_PREFIX


def _risk_submissions():
    return (
        select(InspectionSubmission)
        .join(InspectionForm, InspectionForm.id == InspectionSubmission.form_id)
        .where(InspectionForm.kind == InspectionKind.risk)
        .options(
            selectinload(InspectionSubmission.risk_zones),
            selectinload(InspectionSubmission.risk_summary),
            selectinload(InspectionSubmission.location),
        )
        .order_by(
            InspectionSubmission.inspected_at.desc().nulls_last(),
            InspectionSubmission.gocanvas_submission_id.desc(),
        )
    )


def list_for_company(db: Session, company_id: uuid.UUID) -> list[InspectionSubmission]:
    """Risk inspections of every location under the company's bill-tos, newest first."""
    return list(
        db.scalars(
            _risk_submissions()
            .join(Location, Location.id == InspectionSubmission.location_id)
            .join(BillTo, BillTo.id == Location.bill_to_id)
            .where(BillTo.company_id == company_id)
        )
    )


def list_for_bill_to(db: Session, bill_to_id: uuid.UUID) -> list[InspectionSubmission]:
    """Risk inspections of the bill-to's locations, newest first."""
    return list(
        db.scalars(
            _risk_submissions()
            .join(Location, Location.id == InspectionSubmission.location_id)
            .where(Location.bill_to_id == bill_to_id)
        )
    )


def list_for_location(db: Session, location_id: uuid.UUID) -> list[InspectionSubmission]:
    return list(
        db.scalars(_risk_submissions().where(InspectionSubmission.location_id == location_id))
    )


def get(db: Session, submission_id: uuid.UUID) -> InspectionSubmission | None:
    """A risk inspection by our id (None if missing or not a risk inspection)."""
    return db.scalar(_risk_submissions().where(InspectionSubmission.id == submission_id))


def list_item(submission: InspectionSubmission) -> RiskInspectionListItem:
    inspected = [z for z in submission.risk_zones if z.inspected == "yes"]
    risks = [z.overall_risk for z in inspected if z.overall_risk is not None]
    summary = submission.risk_summary
    return RiskInspectionListItem(
        id=submission.id,
        gocanvas_submission_id=submission.gocanvas_submission_id,
        submission_number=submission.submission_number,
        inspected_at=submission.inspected_at,
        inspector_name=submission.inspector_name,
        store_label=submission.store_label,
        location_id=submission.location_id,
        location_name=trail.location_name(submission.location) if submission.location else None,
        work_order_ref=submission.work_order_ref,
        service_order_id=submission.service_order_id,
        ramp_recommendation=summary.ramp_recommendation if summary else None,
        highest_risk=max(risks, default=None),
        zones_inspected=len(inspected),
        zones_with_activity=sum(1 for z in inspected if z.has_activity),
        is_revision=submission.is_revision,
        revised_at=submission.revised_at,
    )


def detail(db: Session, submission: InspectionSubmission) -> RiskInspectionDetail:
    values = db.scalars(
        select(InspectionPhotoValue)
        .where(
            InspectionPhotoValue.submission_id == submission.id,
            InspectionPhotoValue.removed_at.is_(None),
        )
        .options(selectinload(InspectionPhotoValue.photos).selectinload(InspectionPhoto.file))
        .order_by(InspectionPhotoValue.entry_id)
    ).all()
    photos: dict[str | None, list[RiskInspectionPhoto]] = defaultdict(list)
    for value in values:
        for photo in value.photos:
            photos[value.zone_key].append(
                RiskInspectionPhoto(
                    file_id=photo.file_id,
                    category=value.category,
                    position=photo.position,
                    file_name=photo.file_name,
                )
            )
    location = submission.location
    company_id = (
        db.scalar(select(BillTo.company_id).where(BillTo.id == location.bill_to_id))
        if location
        else None
    )
    summary = submission.risk_summary
    # Materials in the form's order, as the PDF lists them.
    form_order = {f.field_key: f.position for f in submission.form.fields if f.field_key}
    return RiskInspectionDetail(
        **list_item(submission).model_dump(),
        trail=trail.trail(
            db,
            operator_id=submission.operator_id,
            company_id=company_id,
            bill_to_id=location.bill_to_id if location else None,
            location_id=location.id if location else None,
        ),
        address=submission.address,
        city=submission.city,
        manager_summary=summary.manager_summary if summary else None,
        material_notes=summary.material_notes if summary else None,
        zones=[
            RiskInspectionZoneRead(
                zone_key=z.zone_key,
                name=z.name,
                position=z.position,
                inspected=z.inspected,
                has_activity=z.has_activity,
                all_areas_inspected=z.all_areas_inspected,
                areas=z.areas,
                doors_are=z.doors_are,
                door_sweeps_ok=z.door_sweeps_ok,
                doors_aligned=z.doors_aligned,
                rodent_activity=z.rodent_activity,
                pest_activity=z.pest_activity,
                pest_types=z.pest_types,
                additional_notes=z.additional_notes,
                pest_notes=z.pest_notes,
                sanitation_notes=z.sanitation_notes,
                structural_notes=z.structural_notes,
                sanitation_risk=z.sanitation_risk,
                structural_risk=z.structural_risk,
                overall_risk=z.overall_risk,
                attributes=z.attributes,
                photos=photos.get(z.zone_key, []),
            )
            for z in submission.risk_zones
        ],
        materials=[
            RiskInspectionMaterialRead(
                material_key=m.material_key, name=m.name, used=m.used, quantity=m.quantity
            )
            for m in sorted(
                submission.risk_materials,
                key=lambda m: form_order.get(MATERIAL_PREFIX + m.material_key, len(form_order)),
            )
        ],
        photos_pending=sum(1 for v in values if v.fetched_at is None),
        parse_warning_count=len(submission.parse_warnings),
    )
