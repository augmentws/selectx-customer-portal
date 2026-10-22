# Program Dashboard Plan

Status: proposal, not started · Written 2026-10-21 · Billing is planned separately in [billing-dashboard-plan.md](billing-dashboard-plan.md)

Goal: a dashboard like the Chipotle RAMP Intelligence Portal (`../select-ramp-portal`), built from the data this app collects from PestPac instead of hand-built spreadsheets and Drive extractions, and usable for every customer enrolled in a program.

## Decisions so far

| Question | Decision |
|---|---|
| Where do findings (rodent activity, captures, structural and sanitation conditions) come from? | The PestPac API. Technicians record them there, so findings are synced, not extracted from PDFs. |
| Is RAMP specific to Chipotle? | No. RAMP is a program used for many customers. Programs, enrollment, and metrics are generic, with RAMP as the first program. |
| Customer logins? | Not in the MVP. The dashboard is for Select staff inside the current app; customer access comes later. |
| Billing (the RAMP portal's Cash Register)? | Out of scope here; see [billing-dashboard-plan.md](billing-dashboard-plan.md). |

## The reference: Chipotle RAMP Intelligence Portal

A password-protected static site on Cloudflare Pages. Its data is a set of JSON files built offline:

- `pipeline/EXTRACTION_SPEC.md`: an LLM reads every document in each store's Google Drive folder (service reports, Riskgate inspection forms, proposals, risk assessments) and writes one JSON file per store.
- `pipeline/build_dataset.py` merges those extracts with spreadsheets: the RAMP store tracker, Chipotle's Restaurant Leader Report (org hierarchy), and Chipotle's priority risk lists.
- `public/js/core.js` calculates per-store metrics and the RAMP risk index in the browser.

Current size: 132 stores, about 2,000 visits, 4,400 findings, 2,500 documents.

### What it shows

| Tab | Content | Data behind it |
|---|---|---|
| Overview | Rodent activity from day one; first two weeks vs. day 90 onward; time to rodent-free; services per RAMP; portfolio risk map; stores by risk band; rollout funnel; services and activity by month | Visits, tracker, risk index |
| Store Tracker | Each store's program stage: launch, inspection requested, proposal submitted, approved, phase 1, phase 2, completed | Tracker spreadsheet (maintained by hand) |
| Rodent Activity | Activity by program stage and calendar month; documented captures; where activity was found; stores with recent activity | Visit findings |
| Structural | Findings by type and area; logged vs. remediated by month; open vulnerabilities | Structural findings with open/repaired status |
| Sanitation & Pests | Concerns by type and area; secondary pests; share of visits with concerns; stores with recurring concerns | Sanitation and pest findings |
| Stores | Services per store; store scorecard; RAMP risk index and band | Calculated from the above |
| Risk Model | Customer's own risk score vs. field findings; how the index works; customer priority lists | Customer risk lists (spreadsheets) |
| Reports | Library of service reports and other documents | Google Drive |

### The RAMP risk index

Per store, over the 90 days before its latest rated visit (0–100):

| Component | Points | Measure |
|---|---|---|
| Rodent activity | 40 | Mean activity score (none 0 … heavy 3) / 3 |
| Open structural vulnerabilities | 25 | Open findings logged in the window, capped at 6 |
| Sanitation | 20 | Share of visits with sanitation concerns |
| Secondary pests | 15 | Share of visits with other pests |

Bands: Critical ≥ 55, High ≥ 35, Elevated ≥ 20, otherwise Controlled. Stores with no rated visits are "No Service Data".

The visit record behind most charts (from the extraction spec): date, visit type, technician, rodent activity level, species, evidence, captures, activity locations, other pests with severity, structural findings (location, issue, category, open/repaired), sanitation findings (location, issue, category, severity), sanitation rating, exclusion status, devices serviced, materials used, work performed, recommendations, summary.

## What we have vs. what's missing

✅ have · ⚠️ partial · ❌ not synced yet

| Dashboard needs | Status | Source |
|---|---|---|
| Store list, address, phone, map coordinates | ✅ | `locations` |
| Store number and display name ("Grand Central") | ⚠️ Store number is only inside `Company` ("CHIPOTLE - STORE #436") | Parse the number; display name as a customer attribute |
| Customer org hierarchy (region, sub-region, team director, executive team director, restaurant leader) | ❌ | Customer CSV import |
| Service history: dates, technicians, worked (posted) and billed (closed) | ✅ | `service_orders`, `technicians` |
| Visit type (monitoring, exclusion, mass trapping, QC inspection, risk assessment, …) | ⚠️ Raw `ServiceCode` only (e.g. `RAMP 1`, `RAMP MONITOR`, `SPINSPCHG`, `SPRODENTMASS`) | A service code → visit type mapping we maintain per operator |
| Rodent activity level, species, evidence, captures, activity locations | ❌ | PestPac devices and device pest findings (`/Locations/{id}/devices`, device `pestFindings`) |
| Structural findings with open/repaired status | ❌ | PestPac Conditions (`/Locations/{id}/conditions`, with inspections and completion) |
| Sanitation findings and secondary pests | ❌ | PestPac Conditions and pest findings |
| Materials used | ❌ | `/Locations/{id}/materialApplications` |
| Technician comments | ❌ `TechnicianComment` is in the order body but not stored | Service order |
| Service report PDFs | ❌ `PdfUrls` is in the order body but not stored | Service order |
| Riskgate inspection (zone risk scores, RAMP recommendation) | ❌ | To confirm: PestPac conditions or inspection records |
| Program tracker (tier, launch, proposal, approval, phase dates, stage) | ❌ | Not in PestPac as far as we know; our own program enrollment records |
| Proposals (tier, price, line items, scope) | ❌ | To confirm in PestPac (proposals or service setups) |
| Customer risk lists (customer risk score, service tickets, closure hours) | ❌ | Customer CSV import |

The PestPac client in `app/integrations/pestpac/` already has Conditions, Devices, and Materials resources, but nothing syncs or stores them yet.

## Plan

### Phase 0: Field mapping

Read-only, against two or three Chipotle locations of the onboarded bill-to. No schema changes.

- Pull conditions (with their inspections), devices with pest findings, material applications, and a full service order body (`TechnicianComment`, `PdfUrls`).
- Map each RAMP portal visit field to the PestPac field that holds it, using the same stores' extracts in `select-ramp-portal/pipeline/extract/<store>.json` as the reference.
- Check the condition, device, and pest-finding lookups (`/lookups/conditions/*` and similar) to build category mappings.
- Confirm where Riskgate inspections, RAMP tier, and proposals live, if anywhere in PestPac.
- Check how findings tie to a visit (by service order, or only by date and location) and how far back history goes.

Output: `docs/pestpac-findings-mapping.md`, listing the endpoints, the whitelisted fields to store, how each maps to dashboard measures, and paging and volume per location.

### Phase 1: What we can show now

- Store directory: parse the store number from the location name; add an editable display name.
- Service code → visit type mapping: an operator-level table edited by admins; unmapped codes show as "Other".
- Service timeline per store and per month, technicians, days since last service, open and worked orders.
- Store `TechnicianComment` and `PdfUrls` on service orders (migration). Link report PDFs from the location page.

### Phase 2: Findings sync

- New tables for what Phase 0 confirms, likely conditions (with inspection history and status), devices, device pest findings, and material applications, each keyed by PestPac id, scoped by operator, and linked to locations and, where PestPac links them, service orders.
- Synced in the background worker after each location's orders and notes, following the existing sync-job pattern: fetch before write, commit per location, a failure in one kind never undoes another.
- Webhooks: extend the stub's handlers once Phase 0 shows which events carry findings.
- A normalized view over these tables gives the dashboard one shape: location, date, kind (rodent activity, structural, sanitation, pest), category, area, severity, status.

### Phase 3: Programs and program data PestPac doesn't have

Programs are generic: RAMP is the first, and any customer can be enrolled.

- `programs`: per operator; name, description, stage definitions (ordered stages and milestone names), tiers, and which risk index applies.
- `program_enrollments`: a location (or bill-to) in a program, with tier, current stage, and milestone dates. Editable in the app and importable from CSV, replacing the tracker spreadsheet. Where PestPac data implies a milestone (first service of a code, first monitoring visit), suggest it rather than overwrite manual entries.
- Customer attributes: per-company custom fields on locations (region, sub-region, team directors) defined by a schema, with CSV import, so the dashboard can group by the customer's own hierarchy.
- Customer risk lists: importable per company, kept separate from our own metrics.

### Phase 4: Metrics

- Per-location metrics calculated on the backend after each sync: risk index and band, activity rate, days since activity, time to rodent-free, open structural findings, services and inspections.
- Stored in a summary table refreshed by the worker; dashboard endpoints return aggregates by program, company, customer region, and month, so the browser does no heavy calculation.
- The risk index belongs to the program and is versioned (formula, weights, bands), since customers compare numbers over time. RAMP starts with the formula above.

### Phase 5: Dashboard for Select staff

- A new dashboard area in the current app: pick a program, then filter by company, region, and stage. Tabs follow the RAMP portal (overview, tracker, rodent activity, structural, sanitation and pests, stores, risk model, reports).
- Permission-gated like everything else (a new `dashboards:read` permission for the operator roles).
- A charting library for the web app (new dependency; Recharts is the one shadcn's chart components use) and a map for the risk map.
- The report library links service report PDFs and the PDF reports from `report_templates`.

### Later: Customer access

Customer logins (deferred in `AGENTS.md`): customer users scoped to a company, a read-only customer role, and a separate route group that reuses the Phase 5 dashboard limited to their company. No dashboard work should assume staff-only access, so this stays a matter of scoping rather than a rebuild.

## Open questions

1. Riskgate inspections and proposals: are they in PestPac (and where), or do they stay outside this?
2. Program stages and milestones: is the RAMP stage list (launch, inspection requested, proposal submitted, approved, phase 1, phase 2, completed, monitoring) the same for every RAMP customer?
3. Keep the RAMP risk index formula as is, or revisit it?
4. Customer hierarchy and risk lists: is CSV import enough, or do some customers provide them another way?

## Recommended next step

Phase 0 against two or three Chipotle locations, producing the field mapping.
