# Plan: contacts, abatement programs, and risk inspection → chargeable inspection

Status: revised Oct 29 with the decisions below. Nothing is built. Branch: `feature/contacts-abatement-programs`.

## Decisions (Oct 29)

- **A location can have more than one abatement program.** No uniqueness on location + program type.
- **Program type** is an enum: `RAMP` (Rodent Abatement & Mitigation Program), `IAMP` (Insect Abatement & Mitigation Program) or `NRO` (New Restaurant Opening).
- **"Romeo 2" → IAMP.** When a tracker row has a date in the "Romeo 2" column, the store gets a **second program** of type `IAMP`, alongside its RAMP. The IAMP's start date (`phase_1_started_on`) is the "Romeo 2" date; its other dates stay empty. (The column is empty today, so none are created yet.)
- **Tier** is just `tier`: 1, 2 or 3. Not "RAMP Tier".
- **Phases** are generic: `phase_1_started_on`, `phase_2_started_on`, not RAMP-specific.
- **NRO** is its own program type. Tracker rows with tier "NRO" become `NRO` programs with the row's dates and no tier (3 today: #4927, #5939, #6282).
- **Location description.** Add `locations.description`, ours, never written by PestPac syncs. Fill it with the store name, e.g. "Grand Central - 436". The tracker has no store-name column, so the name comes from the Leader Report's name column.
- **Leader Report: only OPEN stores are imported.** PROJECT rows are ignored entirely (16 of our locations are PROJECT in this export; they get no contacts or description).
- **Contacts are visible to everyone** who can see the location or bill-to. No separate `contacts:read` permission; they follow `bill_tos:read`, plus company users on their own company's locations once customer access to locations exists.
- **No risk inspection → chargeable order matching yet.** Section 3 is on hold while it's investigated.
- **Other tracker tiers** (Entomology Walk, Risk Assessment, blank): left out for now (see open question).

## Goals

1. A generic **Contact** that can be linked to bill-tos and locations. The first source is Chipotle's Restaurant Leader Report, linked to locations.
2. **Abatement programs** on a location, of three types:
   - **RAMP**: Rodent Abatement & Mitigation Program
   - **IAMP**: Insect Abatement & Mitigation Program (the tracker's "Romeo 2" column)
   - **NRO**: New Restaurant Opening

   The first source is the Chipotle RAMP Store Tracker.
3. Link each GoCanvas **risk inspection** to the location's **chargeable inspection** service order.

**Rule for every import:** only rows that match a location we already hold are imported. Everything else is reported and skipped. No location is ever created from a spreadsheet.

## What the data looks like today (local DB, Oct 29)

| Source | Rows | Match an existing location |
|---|---|---|
| PestPac Chipotle locations | 546 with a store number (`... #<n>`) | — |
| Restaurant Leader Report | 4,122 stores | 540 |
| RAMP Store Tracker | 127 stores, one row each | 126 (#230 missing) |
| GoCanvas risk inspections | 437 submissions, 429 linked to a location | — |
| Chargeable inspection orders (`SPINSPCHG` "INSPECTION-CHARGEABLE", plus 1 `INSP-CHARGE`) | 521 orders, 323 locations | — |

- Risk inspections linked to an order today: 53, all by Work Order number. 49 of those are `SPINSPCHG`. The other 4 point at RAMP or mass-trapping orders.
- Of the 429 located submissions, 212 have a chargeable inspection at their location. 179 have one on the same day and 187 within ±1 day. Widening to ±7 days adds only one more.
- The tracker's "Romeo 2" column is **empty** for every store. "Entomology Walkthrough" is filled for 4 stores and "Service Completed" for 13.

## 1. Contacts

### Tables (one migration)

`contacts`: one person or mailbox per operator.

| Column | Notes |
|---|---|
| `id`, `operator_id` | Every operator-owned row carries `operator_id` |
| `company_id` (nullable) | The customer they belong to (Chipotle), for scoping |
| `name`, `email`, `phone` | `email` lower-cased |
| `source` | `restaurant_leader_report`, later `manual` / `pestpac` |
| `source_key` | Dedupe key. Email when present, else name + phone |
| `created_at`, `updated_at`, `removed_at` | Never hard-deleted |

Unique on `(operator_id, source, source_key)`. The same Team Director across 40 stores is one contact with 40 links.

`contact_links`: one contact attached to one object, in a role.

| Column | Notes |
|---|---|
| `id`, `operator_id`, `contact_id` | |
| `location_id`, `bill_to_id` | Nullable FKs. A check constraint requires **exactly one**. More object types later means more nullable FKs, the same way `notes` does it |
| `role` | `executive_team_director`, `team_director`, `restaurant_leader`, `store` (the restaurant's own phone and email) |
| `source`, `imported_at`, `removed_at` | A link the next import no longer contains gets `removed_at` |

Unique on `(contact_id, location_id, bill_to_id, role)`.

### Import

`python -m app.import_leader_report --operator-id ... --company-id ... <csv>`

1. Read the rows by column position. The export has no header row; the column map lives in one place in the importer, with a check that the first data row looks right.
2. Match each store number to exactly one location (`pestpac_company` ending `#<n>`, the same rule as the risk inspection link).
3. For each match, upsert up to 4 contacts and their links: ETD, TD, Restaurant Leader, and the store's own phone and email.
4. Mark links from this source that are no longer in the file as removed.
5. Print a summary: matched, unmatched (for example, the 3,582 stores we don't serve), and contacts created, updated and removed.

### API and UI

- `GET /v1/locations/{id}/contacts` and `GET /v1/bill-tos/{id}/contacts`.
- A "Contacts" tab on the location page, and later on the bill-to page.
- Visible to everyone who can see the location or bill-to (no separate permission).

### Policy change

`AGENTS.md` currently says contact names are not stored for locations. This plan changes that, for contacts supplied by the customer, not PestPac's contact fields. `AGENTS.md` gets updated in the same change.

## 2. Abatement programs

### Table

`abatement_programs`: one program run at one location.

| Column | Notes |
|---|---|
| `id`, `operator_id`, `location_id` (FK) | |
| `program_type` | Enum `RAMP` \| `IAMP` \| `NRO` |
| `tier` | Smallint 1–3 (from "RAMP 1/2/3"), check constraint; null for IAMP and NRO |
| `launched_on` | |
| `inspection_requested_on`, `proposal_submitted_on`, `approved_on` | |
| `entomology_walk_on` | |
| `phase_1_started_on` | Program start: abatement for RAMP/NRO, the "Romeo 2" date for IAMP |
| `phase_2_started_on` | Monitoring (6 months) |
| `completed_on` | |
| `stage` | Derived on read from the dates (Inspection requested → Awaiting approval → Approved → Active abatement → Monitoring → Monitoring 6+ months → Completed), not stored |
| `notes` | The tracker's first column, e.g. "RA: 9/14/2026" |
| `source`, `source_row`, `imported_at` | |

No uniqueness on location + program type: a location can have several programs over time. Re-imports find their row by `(source, source_key, program_type)`, where `source_key` is the store number plus launch date from the tracker row.

### Import

`python -m app.import_abatement_tracker --operator-id ... <csv>`

1. The section headers ("State, Store #, …") repeat per state; those rows are skipped.
2. Match each store number to a location. Unmatched stores (today #230) are reported.
3. Dates are parsed `M/D/YYYY`. A date in the future is **reported, not rewritten**. (The RAMP portal silently moves such dates back a year, which breaks as time passes.)
4. Each tracker row with a RAMP 1/2/3 tier upserts a `RAMP` program; a row with tier "NRO" upserts an `NRO` program. A date in "Romeo 2" also upserts an `IAMP` program for the same location, started on that date. Rows with other tiers (Entomology Walk, Risk Assessment, blank) are reported and skipped.

### API and UI

- `GET /v1/locations/{id}/abatement-programs`, with `bill_tos:read`.
- An "Abatement programs" panel on the location's Overview, and a programs column on the bill-to's locations table.

## 3. Risk inspection → chargeable inspection order (ON HOLD: investigating)

Change `_link` in `app/services/inspections.py`:

1. **Work Order ID.** If it's a number and matches an order whose service code is a chargeable inspection, link it.
2. **Otherwise**, find the location (Work Order's order, else the store number, as now). Then link the location's chargeable inspection order with the nearest WorkDate within ±1 day of `inspected_at`, if one exists.
3. **One order per inspection, one inspection per order.** If two submissions want the same order, the nearer date wins and the other is left unlinked.
4. Chargeable codes are a setting, `CHARGEABLE_INSPECTION_SERVICE_CODES` (default `SPINSPCHG,INSP-CHARGE`), not hard-coded.
5. A Work Order pointing at a non-inspection order (4 today) still sets the location, but not the order.
6. Add `python -m app.load_inspections --relink` to re-run linking over stored submissions. Linking happens again on each order sync, so an inspection whose order arrives later still gets linked.

Expected result today: about 187 of 429 located inspections linked to a chargeable order. The others have no chargeable order in our copy (PestPac only lists orders since onboarding). Those should improve as invoices backfill orders.

## Order of work (each step is its own commit, with tests)

1. `locations.description` (migration, model, API, shown on the location page; PestPac syncs never write it).
2. Contacts: migration, models, Leader Report importer (OPEN stores matching a location; also fills `description`), API, location tab, access matrix, `AGENTS.md`.
3. Abatement programs (RAMP, IAMP, NRO): migration, model, tracker importer, API, location panel.
4. Risk inspection → chargeable order linking: after the investigation.

Each step runs `ruff`, `pytest`, `alembic check`, and an upgrade/downgrade on a scratch DB. Frontend steps also run `pnpm typecheck`, `pnpm lint`, `pnpm build` and `pnpm api:generate`.

## Open questions

- **Other tracker tiers**, left out for now:
  - `Entomology Walk` (#3168, #1084, #3094): requested, approved, walk and completed all on Jul 8–9.
  - `Risk Assessment` (#1928): requested and submitted only.
  - Blank tier (9 stores): only early steps filled (launch / requested / submitted). #402 has "*Drain Cleaning" in the Phase 1 column and a completed date.
