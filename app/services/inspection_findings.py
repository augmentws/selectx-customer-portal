"""Findings from a service visit: what the technician's notes say was found and done, as data.

The LLM reads them in the same call that drafts a service report (`service_reports.run_draft`
adds `INSTRUCTIONS` and `FindingsOut` to the template's own prompt and fields), so the rules
here are the same whichever template is used. They're stored in `inspection_findings`, one
current row per service order, replaced when they're read again. They're internal: the
narrative never shows their levels or severities.
"""

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.openrouter import Usage
from app.models import InspectionFinding, InspectionFindingItem

# Bump when INSTRUCTIONS or FindingsOut change in a way that changes what's extracted.
METHOD_VERSION = 1

VisitType = Literal[
    "risk_assessment",
    "initial_service",
    "exclusion",
    "mass_trapping",
    "monitoring",
    "qc_inspection",
    "follow_up",
    "entomology_walk",
    "cleanout",
    "other",
]
Level = Literal["low", "moderate", "heavy"]
Evidence = Literal[
    "droppings",
    "capture",
    "live sighting",
    "gnaw marks",
    "rub marks",
    "burrows",
    "nesting",
    "dead rodent",
    "tracks",
]
StructuralCategory = Literal[
    "wall/floor gap",
    "utility penetration",
    "door/door sweep",
    "drain",
    "ceiling/drop ceiling",
    "foundation",
    "equipment void",
    "roof/exterior",
    "shared wall/adjacent tenant",
    "dumbwaiter/elevator",
    "other",
]
SanitationCategory = Literal[
    "clutter/debris",
    "food residue",
    "grease buildup",
    "trash/dumpster",
    "standing water/moisture",
    "improper storage",
    "drains",
    "other",
]
Pest = Literal[
    "German cockroach",
    "American cockroach",
    "fruit fly",
    "drain fly",
    "house fly",
    "ants",
    "stored product pest",
    "other",
]

_TEXT = Field(max_length=500)


class StructuralFindingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str = _TEXT
    issue: str = _TEXT
    category: StructuralCategory
    status: Literal["open", "in_progress", "repaired"]


class SanitationFindingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str = _TEXT
    issue: str = _TEXT
    category: SanitationCategory
    severity: Level


class PestFindingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pest: Pest
    severity: Level
    location: str | None = _TEXT


class FindingsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visit_type: VisitType
    rodent_activity: Literal["none", "low", "moderate", "heavy"] | None
    rodent_species: list[Literal["rat", "mouse"]]
    rodent_evidence: list[Evidence]
    rodents_captured: int | None = Field(ge=0)
    activity_locations: list[str]
    devices_serviced: int | None = Field(ge=0)
    exclusion_status: Literal["intact", "compromised"] | None
    sanitation_rating: Literal["satisfactory", "needs_improvement", "poor"] | None
    structural_findings: list[StructuralFindingOut]
    sanitation_findings: list[SanitationFindingOut]
    other_pests: list[PestFindingOut]
    summary: str = Field(max_length=1000)


INSTRUCTIONS = """FINDINGS
Besides the report, fill `findings`: the same visit as data, for Select's internal tracking. Take it
from the notes, never from your own narrative, and follow the same evidence rules: when the notes
don't say, use null or an empty list. The levels and severities here are internal and never appear
in the narrative.
- visit_type: risk_assessment, initial_service, exclusion, mass_trapping, monitoring, qc_inspection,
  follow_up, entomology_walk, cleanout, or other; use the service order's code and description as
  well as the notes.
- rodent_activity: none when the notes say no activity was found; heavy for heavy, significant,
  widespread, or infestation; moderate for active, several, or multiple; low for minor, isolated, or
  single. Null when the notes don't assess it.
- rodent_species: rat and/or mouse, only when named.
- rodent_evidence: the kinds of evidence the notes report (droppings, capture, live sighting, gnaw
  marks, rub marks, burrows, nesting, dead rodent, tracks).
- rodents_captured: only a number the notes state; else null.
- activity_locations: where activity was found, short phrases (e.g. "serving line motor
  compartment").
- devices_serviced: only a number the notes state; else null.
- exclusion_status: intact or compromised, only when the notes assess it.
- sanitation_rating: satisfactory, needs_improvement, or poor, only when the notes rate it or
  clearly describe it.
- structural_findings: one per opening or vulnerability (location, issue, category, status). Status
  is repaired only when the notes confirm the repair, in_progress when partly done, otherwise open.
- sanitation_findings: one per condition (location, issue, category, severity).
- other_pests: one per non-rodent pest reported (pest, severity, location).
- summary: one or two plain sentences on what was found and done."""


def describe() -> str:
    """The output description for `findings`, added after the template's field list."""
    return "- findings (object): the visit as data, as described under FINDINGS."


def save(
    db: Session,
    *,
    operator_id: uuid.UUID,
    service_order_id: uuid.UUID,
    location_id: uuid.UUID | None,
    report_id: uuid.UUID | None,
    source: Literal["report_draft", "extraction"],
    findings: FindingsOut,
    model: str,
    usage: Usage,
) -> InspectionFinding:
    """Store the order's findings, replacing any it had. Doesn't commit."""
    row = db.scalar(
        select(InspectionFinding).where(InspectionFinding.service_order_id == service_order_id)
    )
    if row is None:
        row = InspectionFinding(operator_id=operator_id, service_order_id=service_order_id)
        db.add(row)
    row.location_id = location_id
    row.report_id = report_id
    row.source = source
    row.visit_type = findings.visit_type
    row.rodent_activity = findings.rodent_activity
    row.rodent_species = list(findings.rodent_species)
    row.rodent_evidence = list(findings.rodent_evidence)
    row.rodents_captured = findings.rodents_captured
    row.activity_locations = findings.activity_locations
    row.devices_serviced = findings.devices_serviced
    row.exclusion_status = findings.exclusion_status
    row.sanitation_rating = findings.sanitation_rating
    row.summary = findings.summary or None
    row.model = model
    row.method_version = METHOD_VERSION
    row.usage = dataclasses.asdict(usage)
    row.extracted_at = datetime.now(UTC)

    items = [
        InspectionFindingItem(
            kind="structural",
            category=s.category,
            location=s.location,
            issue=s.issue,
            status=s.status,
        )
        for s in findings.structural_findings
    ]
    items += [
        InspectionFindingItem(
            kind="sanitation",
            category=s.category,
            location=s.location,
            issue=s.issue,
            severity=s.severity,
        )
        for s in findings.sanitation_findings
    ]
    items += [
        InspectionFindingItem(
            kind="pest", category=p.pest, location=p.location, severity=p.severity
        )
        for p in findings.other_pests
    ]
    for position, item in enumerate(items):
        item.position = position
    row.items = items
    db.flush()
    return row
