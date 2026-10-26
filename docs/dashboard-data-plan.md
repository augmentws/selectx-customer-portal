# Dashboard Data Plan

Status: proposal · Written 2026-10-25 · Builds on [customer-dashboard-plan.md](customer-dashboard-plan.md), whose "what we have" table predates notes, technician comments, invoices, documents, and conditions being synced.

Question: does the data we hold today support the customer-facing dashboards of the Chipotle RAMP Intelligence Portal (`../select-ramp-portal`), and if not, what do we have to ingest?

Short answer: **partly**. We hold the stores, the visits, and the raw text the portal's findings were extracted from, for the same period. We don't hold the findings themselves (the portal extracted them with an LLM from Drive PDFs), the program tracker, the customer's org hierarchy, the customer's risk lists, or Riskgate inspections. Rodent activity, sanitation and pests, structural findings, the store scorecard, and most of the overview can be built after one ingestion step (findings extracted from text we already hold); the tracker, the customer's hierarchy and risk lists, and Riskgate need data from outside PestPac.

Scope: the client portal (`/`). SEAL Team Oversight (internal) and the Cash Register (billing, see [billing-dashboard-plan.md](billing-dashboard-plan.md)) are not covered.

## What the portal is built from

| File | Rows | Built from |
|---|---|---|
| `stores.json` | 132 | Tracker sheet + Chipotle's Restaurant Leader Report + Riskgate + Chipotle risk lists + Drive folder |
| `visits.json` | 1,996 | LLM extraction of every service report PDF in each store's Drive folder (`pipeline/EXTRACTION_SPEC.md`) |
| `findings.json` | 4,439 | Same extraction: one row per structural, sanitation, or pest finding (kind, category, area, issue, status, severity) |
| `tracker.json` | 127 | `Chipotle_RAMP_Store_Tracker.csv`, kept by hand: tier, launch, inspection requested, proposal submitted, approved, phase 1, phase 2, completed, stage |
| `riskgate_zones.json` | 524 | Riskgate inspection forms: per zone, rodent and pest activity, sanitation, structural and overall risk (1–5) |
| `chipotle_risk.json` | 100 | Chipotle's priority risk lists (`Rodent_Risk_Assessment_Tekashi_*.csv`): rank, service tickets, closure hours, risk scores |
| `documents.json` | 2,486 | Drive folder listing (service reports, proposals, Riskgate forms, risk assessments) |
| `assessment_progress.json` | 7 | Stores in program vs. assessed, per state (hand-entered) |

The risk index and every chart are calculated in the browser from these files.

## What we hold today (dev database, Chipotle bill-to)

| Data | Count | Notes |
|---|---|---|
| Locations | 546, all geocoded | Store number in every name (`CHIPOTLE - STORE #2254`). **131 of the portal's 132 stores match.** |
| Service notes (`SERVICE`) | 3,234 (3,075 on RAMP stores, 128 of 131) | Nov 2025 – Oct 2026: the portal's whole period. The technicians' narrative: activity, sanitation, structural, work done. |
| Alert notes (`ALERT`, `HHALERT`) | 512 | Access and hours ("Store closes at 10pm"); routing data, not findings |
| Service orders | 1,485 (1,066 worked, 999 billed) | From Feb 2026 only: PestPac lists open orders, so older ones exist only if a webhook or invoice led to them. 98 of 131 RAMP stores. |
| Technician comments | 911 orders | Same narrative as the order's service note, usually |
| Invoices | 991 | With line items and totals |
| Service codes | `RAMP MONITOR` 711, `SPINSPCHG` 433, `RAMP 2` 76, `RAMP 3` 72, `SPRODENTPICKUP` 59, `SPRODENTMASS` 34, `RAMP 1` 26, … | Visit type is implied by the code; no mapping yet |
| Documents | 43, one location | "Documents and conditions" has run for one Chipotle location only |
| Conditions | 0 for Chipotle (2 in the whole database) | Same: not synced across the bill-to, so we don't know yet whether technicians record conditions |
| Devices, material applications | not synced | Client methods exist (`/Locations/{id}/devices`, `/Devices/{id}/pestFindings`, `/Locations/{id}/materialApplications`) |
| GoCanvas | 6 requests, ~150 bytes each | Notifications only, not form data. Some service notes just say "See Brandon's gocanvas". |
| Our service reports | a handful | Drafted from notes + technician comment |

Spot check of visit dates (portal visit vs. a service note the same day): store 436, 63 portal visits, 75 note days; store 2254, 6 vs. 9; store 1394, 19 vs. 24. Most misses are a day apart: night services are written up after midnight, so visits must be matched to notes with a one-day tolerance.

## Tab by tab

✅ supported now · 🟡 supported after an ingestion step listed below · ❌ needs data from outside PestPac

| Tab | Needs | Status | Ingest |
|---|---|---|---|
| **Overview** | Activity from day one; first two weeks vs. day 90+; time to rodent-free; services per tier; risk map; stores by risk band; rollout funnel; services and activity by month | 🟡 activity, services, map · ❌ funnel, tier | D1, D2, D3 (funnel and tier: D5) |
| **Store Tracker** | Program stage and milestone dates per store | ❌ | D5 (D2 can suggest some dates) |
| **Rodent Activity** | Activity level, species, evidence, captures, areas, by stage and month | 🟡 | D1 (by stage: D5) |
| **Structural** | Findings by type and area; logged vs. remediated by month; open vulnerabilities | 🟡 logged · ⚠️ remediated | D1 + D4 (status over time is the hard part, see below) |
| **Sanitation & Pests** | Concerns by type and area; secondary pests; share of visits with concerns; recurring stores | 🟡 | D1 |
| **Stores** | Services per store, scorecard, risk index and band, region | 🟡 · ❌ region, directors | D1, D3 (region: D6) |
| **Risk Model** | Chipotle's own risk score vs. field findings; customer priority lists | ❌ | D7 (field side: D1) |
| **Reports** | Library of service reports and other documents | 🟡 | D8 |
| Riskgate zone scores (Overview, Stores) | Zone risk 1–5, RAMP recommendation | ❌ | D9 |

## Data to ingest

Ordered by how much of the dashboard each unlocks.

### D1. Visit findings, extracted from the text we already hold (unlocks most charts)

The portal's findings came from an LLM reading service report PDFs. The same narrative is in PestPac as service notes and technician comments, which we already sync, so we can extract findings ourselves with the existing `run_task` (OpenRouter) in the worker.

- **Unit:** one *visit* per location and work date. Its sources are the worked order(s) that day and the `SERVICE` notes within a day of it; for dates before we stored orders (before Feb 2026), the notes alone.
- **Output:** the extraction spec's visit record, minus what text can't give: visit type (from D3), activity level (none/low/moderate/heavy), species, evidence, captures (only stated numbers), activity areas, other pests with severity and area, structural findings (area, issue, category, status), sanitation findings (area, issue, category, severity), sanitation rating, exclusion status, devices serviced, materials used, work performed, recommendations.
- **Storage:** `visits` (location, date, linked orders and notes, extraction status, model, prompt version, source hash) and `visit_findings` (kind, category, area, issue, status, severity). Re-extract when a source note or comment changes, or the prompt version changes; never edit by hand without recording it.
- **Rules:** the same "never invent" rules as service reports, plus the lesson from report 4083bf10: a finding is recorded only as specifically as the note states it, and status `repaired` only when a note says the repair was done.
- **Validation:** before trusting it, extract the 131 RAMP stores and compare with `../select-ramp-portal/pipeline/extract/<store>.json` (activity level per visit, finding counts by kind). Agree on an acceptable match rate first.
- **Cost:** about 3,000 notes for RAMP stores, then a few per night. Small; the model choice is the open question.

### D2. Visit history before February 2026

Orders exist only from Feb 2026, but notes go back to Nov 2025. D1's note-only visits cover the gap for the dashboard. If we want orders too (technician, service code, invoice), find a PestPac history source: confirm whether `GET /BillTos/{id}/serviceOrders` or an invoice search by location returns posted or billed history. Phase 0 check, no schema change.

### D3. Service code → visit type (operator setting)

A small table mapping each code to the dashboard's visit types, edited by operator admins. Unmapped codes show as "Other". Proposed starting point, to confirm with Select:

| Code | Visit type |
|---|---|
| `SPINSPCHG`, `SPINSPNOCHG`, `INSP-CHARGE`, `INSP-NO CHARGE` | Risk assessment / inspection |
| `RAMP 1`, `RAMP 2`, `RAMP 3` | Initial service (by tier) |
| `SPRODENTMASS` | Mass trapping |
| `RAMP MONITOR` | Monitoring |
| `SPRODENTPICKUP`, `PICK UP TRAPS` | Trap pickup |
| `Q-C INSPECTION`, `INTQUALINSPECT` | QC inspection |
| `SPESCALATE` | Follow-up / escalation |
| `INTTRAVEL`, `INTEXTRATECH`, `BCREDIT`, `CM` | Not a visit |

It also gives each store's tier (the first `RAMP n` order) and suggested milestone dates for D5: first inspection, phase 1 (first `RAMP n`), monitoring (first `RAMP MONITOR`).

### D4. Documents and conditions across the bill-to

Run the existing "Documents and conditions" sync for the whole Chipotle bill-to (it's on request and has run for one location). Then:

- If technicians record **conditions**, they're the better source for structural findings: they have a status and inspection history, so "logged vs. remediated" comes from PestPac instead of being inferred from text. D1 would then link a finding to its condition, not create its own status.
- If not (likely, given 2 conditions overall), structural status comes from D1: a register per location where a later visit can mark a finding repaired. Expect the remediated numbers to be weaker than the portal's.
- Also check **devices and pest findings** on two or three stores: if trap scans are recorded, they give captures and device counts directly. Only sync them if they hold data.

### D5. Program enrollment and tracker (not in PestPac)

The tracker is Select's own record. Store it as program data, as planned in [customer-dashboard-plan.md](customer-dashboard-plan.md) Phase 3:

- `programs` (RAMP: ordered stages and milestone names, tiers) and `program_enrollments` (location, tier, stage, milestone dates, note).
- One-off import of `Chipotle_RAMP_Store_Tracker.csv` (127 stores), then edited in the app; D3 suggests dates, never overwrites entered ones.
- `assessment_progress` (stores in program vs. assessed, per state) can be calculated: the bill-to's locations per state already match the portal's "in program" counts (NY 250 vs. 248, PA 154 vs. 150, MA 83 vs. 82, DC 21 vs. 19), and "assessed" is a location with an inspection visit (D3) or an enrollment past the inspection stage.

### D6. Customer hierarchy and store names (from the customer)

From Chipotle's Restaurant Leader Report (`Restaurant_Leader_Report.csv`): store display name ("Grand Central"), sub-region, team director, executive team director, real estate type. Per-company location attributes with a CSV import, as in the earlier plan. Matched by store number, which every location name carries.

### D7. Customer risk lists (from the customer)

Chipotle's priority lists (`Rodent_Risk_Assessment_Tekashi_34.csv`, `_66.csv`): rank, service tickets in 6 months, closure hours, EcoLab findings, restaurant and overall risk scores, RiskKey level. Imported per company and dated, kept apart from our own metrics. Only needed for the Risk Model tab.

### D8. Report library

- PestPac documents (after D4), served as today.
- Our finalized service reports (already stored as PDFs).
- The Drive archive (2,486 documents) is outside PestPac. Either leave history in Drive and link each store's folder (a URL attribute per location, from the manifest), or import it once. Recommend linking: the files themselves aren't needed for the charts once D1 exists.

### D9. Riskgate inspections and GoCanvas forms

The Riskgate form (zone-by-zone risk scores, RAMP recommendation, work order) and many service reports are GoCanvas forms, which explains notes like "See Brandon's gocanvas". GoCanvas currently sends us ~150-byte notifications, not the form. Next step: read one stored notification, and if it carries a submission id, fetch the submission through the GoCanvas API (per-operator credentials, like PestPac). That would give Riskgate zones directly and a richer D1 source than notes. Until then, Riskgate data could be imported once from the existing extracts (`riskgate_zones.json`).

## Order of work

1. **Checks, no schema change:** run "Documents and conditions" for the Chipotle bill-to; probe devices, pest findings, and history endpoints on three stores (D2, D4); read a GoCanvas notification (D9).
2. **D3** visit-type mapping, and **D1** on the 131 RAMP stores, compared against the portal extracts. This is the go/no-go for building the dashboard from PestPac.
3. **D5** and **D6** imports (tracker, hierarchy).
4. Metrics and the dashboard (earlier plan, Phases 4–5).
5. **D7**, **D8**, **D9** as the Risk Model, Reports, and Riskgate parts come up.

## Open questions

1. Model and budget for D1 extraction; no OpenRouter model is configured yet.
2. Is the D3 mapping right, and is `SPINSPCHG` the Riskgate inspection?
3. Do technicians record conditions or device scans in PestPac for Chipotle, or only notes (and GoCanvas)?
4. Does GoCanvas give API access to submissions, and is that where Riskgate forms live?
5. Is "in program" every location of the bill-to? The counts per state nearly match (a few stores apart in each state, and NJ 19 vs. 6); which stores account for the difference?
6. Customer-facing means customer logins (deferred). Until then this serves Select staff; no data decision here depends on that.
