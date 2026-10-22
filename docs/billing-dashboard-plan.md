# Billing Dashboard Plan

Status: proposal, deferred · Written 2026-10-21 · Companion to [customer-dashboard-plan.md](customer-dashboard-plan.md)

Goal: replace the RAMP portal's Cash Register (`../select-ramp-portal/public/register/`), an invoice register for the customer's finance team, with billing data synced from PestPac.

## The reference: Cash Register

A separate area of the RAMP portal with its own password, so a portal sign-in doesn't open it. Built by `pipeline/build_register.py` from an Excel invoice register and billing reconciliation workbook.

Current Chipotle figures (as of 2026-10-09): 1,071 invoices across 509 restaurants, 23 credits, about $1.83M net before tax.

| View | Content |
|---|---|
| Headline | Invoice count, restaurants billed, gross, credits, net, tax, total, first and last invoice date |
| Billing by Month | Totals per month |
| Billing by Service Category | Risk Assessments, RAMP 1/2/3, RAMP Monitoring, Credits & Adjustments |
| Billing by Market | Totals by the customer's sub-region |
| Store Register | Per-store totals |
| Invoice Detail | Every invoice, with CSV download |

Each invoice row: invoice number, store, store name, city, state, sub-region, service code (e.g. `SPINSPCHG`, `RAMP 1`, `RAMP MONITOR`), category, date, subtotal, tax, total, credit flag. Account-level charges with no store are shown separately.

## What we have vs. what's missing

| Needs | Status | Source |
|---|---|---|
| Invoice number per worked order | ⚠️ `pestpac_invoice_id`, learned from notes | Notes associations |
| Invoice date, subtotal, tax, total, credit flag | ❌ | PestPac invoices API (to confirm) |
| Invoice lines with service codes | ❌ | PestPac invoices API (to confirm) |
| Service code → billing category | ❌ | A mapping we maintain per operator (shared with the visit-type mapping where codes overlap) |
| Store, city, state | ✅ | `locations` |
| Customer sub-region (market) | ❌ | Customer attributes (Phase 3 of the dashboard plan) |
| Account-level charges (invoices not tied to a location) | ❌ | PestPac invoices billed to the bill-to |

## What this changes

- Data minimization: `AGENTS.md` says we store no pricing, tax, or balances. This feature reverses that for invoices, so the decision and its limits (which amounts, how long they're kept, who sees them) must be recorded there first.
- Access: billing is sensitive and seen by fewer people. A separate permission (`billing:read`) that operator roles don't get by default, and, once customer logins exist, a customer finance role that is distinct from the dashboard role, matching the Cash Register's separate password.

## Plan

1. Discovery (read-only): confirm the PestPac invoice endpoints, their fields, and how they relate to bill-tos, locations, and service orders; check credits and adjustments; check paging and history depth.
2. Decision and docs: record what billing data we store and who may see it in `AGENTS.md`.
3. Sync: an `invoices` table (and `invoice_lines` if lines are needed for categories), whitelisted fields only, keyed by PestPac invoice id per operator, synced in the worker alongside service orders. Link orders to invoices by the existing `pestpac_invoice_id`.
4. Categories: the service code → billing category mapping, editable by operator admins.
5. API: register endpoints returning aggregates by month, category, market, and store, plus paged invoice detail and CSV export, all behind `billing:read`.
6. UI: a Billing area for staff with the views above; customer finance access when customer logins arrive.

## Open questions

1. Which PestPac endpoint is authoritative for invoices, and does it include line items and credits?
2. Who at Select (and later at customers) should see billing?
3. How long should invoice amounts be kept, and should anything be excluded (e.g. payment status, balances)?
4. Does billing need reconciliation features (comparing billed services against worked orders), as the source workbook's name suggests, or only reporting?
