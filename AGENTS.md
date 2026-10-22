# Customer Portal Repository Instructions

These decisions are authoritative for this repository until the user explicitly changes them. Preserve them when designing, implementing, or reviewing work, and update this file when a decision changes.

Bootstrap tier: standard

## Product and Scope

SELECTX customer portal: a web app where customers sign in to view their account and service information, backed by data from the PestPac (WorkWave) API.

This repository holds the backend API and the single web application:

- `app/`: FastAPI application and domain logic
- `app/integrations/pestpac/`: PestPac API client (OAuth2 password grant, per-resource sections). Only the backend calls PestPac. Credentials are per operator, stored encrypted in `pestpac_connections`; build clients with `app.services.pestpac_connection.get_pestpac_client`, never from env vars.
- `alembic/`: database migrations
- `tests/`: backend tests
- `web/`: Next.js application

## Backend Architecture

Use Python 3.14, FastAPI, SQLAlchemy, Alembic, Pipenv, PostgreSQL, and Docker Compose. The local database is named `customer_portal` (tests use `customer_portal_test`). Local ports: PostgreSQL 5433, FastAPI 8001, Next.js 3001.

FastAPI is the authority for domain behavior, authentication, authorization, sessions, and auditing. Do not move domain logic into the UI or its proxy layer.

The OpenAPI document at `/openapi.json` is the API contract. Interactive docs are at `/docs`. The frontend's TypeScript types and client are generated from it with Orval; never hand-edit generated output.

Current API surface (keep the versioned shape unless a contract change is requested):

- `GET /health`
- Auth: `POST /v1/auth/login`, `/refresh`, `/logout`, `/password`; `GET /v1/auth/me` (includes memberships and permissions)
- `GET/POST /v1/operators`, `GET/PATCH /v1/operators/{id}`, `GET/POST /v1/operators/{id}/companies`
- `GET/PATCH /v1/companies/{id}`, `GET/POST /v1/companies/{id}/bill-tos`
- `GET/PATCH /v1/bill-tos/{id}`, `POST /v1/bill-tos/{id}/refresh`, `GET /v1/bill-tos/{id}/locations`, `GET /v1/bill-tos/{id}/service-orders`, `POST /v1/bill-tos/{id}/service-orders/sync`, `GET /v1/bill-tos/{id}/sync-jobs`
- `GET /v1/locations/{id}`, `GET /v1/locations/{id}/notes`, `GET /v1/locations/{id}/service-orders`, `POST /v1/locations/{id}/service-orders/sync`
- `GET /v1/service-orders/{id}`, `GET /v1/service-orders/{id}/notes`, `GET /v1/sync-jobs/{id}`
- `POST /v1/webhooks/pestpac` (public; PestPac webhook deliveries)
- `GET /v1/companies/{id}/bill-tos/lookup`
- `GET/PUT /v1/operators/{id}/pestpac-connection`, `POST /v1/operators/{id}/pestpac-connection/verify`
- `GET/POST /v1/tenants/{id}/members`, `PATCH/DELETE /v1/tenants/{id}/members/{user_id}`
- `GET /v1/roles`, `GET /v1/permissions`

## Tenancy and Data Model

- `tenants` is a tree: exactly one `platform` root (SELECTX, the application admin) with `operator` tenants beneath it. Each operator maps 1:1 to a PestPac tenant (`pestpac_tenant_id`).
- `companies` are our own customer entity (PestPac has none) and belong to one operator.
- `bill_tos` are PestPac bill-tos onboarded to a company. Onboarding happens at the bill-to level; a bill-to may bill a single location, a region, or a whole company (recorded in `description`). `(operator_id, pestpac_bill_to_id)` is unique, and a composite FK keeps a bill-to inside its company's operator.
- Deactivate with `is_active`; don't hard-delete tenants, companies, or bill-tos.
- Every operator-owned row carries `operator_id`; queries are scoped through the services layer.
- Not built yet (keep designs extensible): customer logins, branches, regions, per-operator custom roles.

## PestPac API Access

- Every operator has a required `pestpac_tenant_id`, set by a platform admin when the operator is created. Changing it resets the operator's connection to `unverified`.
- Operator admins (and platform admins) set the operator's PestPac credentials: client ID, client secret, API username/password, and API key. Secrets are Fernet-encrypted with `APP_ENCRYPTION_KEYS` (first key encrypts; all decrypt, for rotation) and are write-only: the API returns only whether each is set and the API key's last 4 characters.
- Saving credentials immediately verifies them: OAuth token, then `GET {base_url}/CompanySetup`. The status (`unverified`/`verified`/`failed`) and the PestPac company name and ID are stored. Error messages never include PestPac response bodies.
- The base URL and token URL come from settings, not from operators, so credentials can't be sent to arbitrary hosts.
- Bill-to onboarding requires a `verified` connection (409 otherwise), and each BillToID must exist in PestPac (`GET /BillTos/{id}`; 422 if not found, 502 if PestPac fails or answers for a different BillToID).
- Onboarding is two steps: `GET /v1/companies/{id}/bill-tos/lookup` previews PestPac's details without storing anything; `POST /v1/companies/{id}/bill-tos` fetches again server side and stores them. `POST /v1/bill-tos/{id}/refresh` re-fetches later and never changes our own `name`/`description`.
- Store only identifying bill-to fields (BillToCode, Company, address, phone, Type), whitelisted in `PestPacBillToDetails`. Don't persist balances, credit/collection data, contacts, or the raw response.
- Onboarding and refresh also sync the bill-to's locations from `GET /BillTos/{id}/locations/pageable` (bare JSON array; a short page ends paging; `PESTPAC_PAGE_SIZE` default 50, `PESTPAC_MAX_PAGES` cap; a page that doesn't advance is an error). Everything is fetched before anything is written, in one transaction.
- Locations are upserted by `(operator_id, LocationID)`: moved locations are reassigned to their new bill-to, and ones PestPac stops listing get `removed_at` (never deleted; service orders will reference them). Kept fields are whitelisted in `PestPacLocationDetails`: LocationCode, Company (the location's name), address, phone, email, Type, AccountType, latitude/longitude, Active. Contact names and user-defined fields (which include staff names) are not stored.
- Locations are read with `bill_tos:read` via `GET /v1/bill-tos/{id}/locations`.

## Service Orders, Technicians, and Notes

- PestPac lists only *open* service orders, per location (`GET /Locations/{id}/serviceOrders`, not paged). `service_orders` is our permanent copy, keyed by `(operator_id, OrderID)`: open (`posted` false) → worked (`Posted` flips true; `posted_at` records when we first saw it) → billed (PestPac stops listing it; `closed_at`). Never delete service orders. Only orders whose BillToID is an onboarded, active bill-to are stored.
- Stored order fields: OrderID, OrderNumber, ServiceCode, Description, WorkDate (PestPac local wall-clock time, no timezone), Tech1, TechID1, Location/Service/Order instructions, Posted, and the InvoiceID learned from the order's notes. No pricing, tax, scheduling windows, or user-defined fields.
- Syncs run in the background worker, `python -m app.worker` (`--once` to drain the queue). `sync_jobs` are claimed with `FOR UPDATE SKIP LOCKED`; stale running jobs are retried up to `SYNC_JOB_MAX_ATTEMPTS`. Each location commits on its own; jobs end `succeeded`, `partial`, or `failed`. Onboarding a bill-to queues its first sync.
- Each job first seeds technicians from `GET /lookups/Employees/technicians` (not paged; not fatal on failure); `GET /lookups/Employees/technicians/{techId}` is the per-job, once-per-tech fallback. A technician problem never fails an order. Store only TechID, EmployeeID, username, first/last name, and Active.
- Notes: one `notes` row per NoteID, mirroring PestPac (a note can be associated with several objects). Objects we model get real foreign keys (`location_id`, `bill_to_id`, `service_order_id`, `created_by_technician_id`); every association is also kept as its raw PestPac id. Don't create per-object note tables.
- Each location's full note history is synced: `GET /Locations/{id}/notes` (skip/take paged), then `GET /Notes/{id}` once per new note for its associations. Known notes are refreshed from the list without a detail call. Posted orders without an InvoiceID have their notes' associations re-checked on later syncs. Notes are synced after the location's orders commit; a notes failure never undoes them.
- `CreatedByUser` links to a technician by username when there is one; otherwise it stays a raw username.
- PestPac calls have timeouts. Request/response bodies contain customer data and are logged only when `PESTPAC_DEBUG_BODIES=true` (local debugging).
- Tests mock PestPac with `responses` (`pestpac` fixture in `tests/conftest.py`); they must never call the real API.

## PestPac Webhooks

- `POST /v1/webhooks/pestpac` is public (no session); the only route exempt from the access matrix besides auth. It answers 200 whether an event was stored, dropped, or a redelivery, so callers can't probe which bill-tos are onboarded; 400 for a malformed envelope, 413 above `WEBHOOK_MAX_BODY_BYTES`.
- Envelope: `TenantId` (matched to `pestpac_tenant_id`), `EntityType`, `EntityId`, `Action`, `EntityBody`. Captured: Bill-To, Employee, Location, Note (create/update/delete) and Service Order (create/update/post/delete); everything else is dropped.
- Signature: HMAC-SHA256 of the serialized `EntityBody` plus the `timestamputc` header, in `signature` headers, keyed by the operator's optional, write-only webhook secret (encrypted on `pestpac_connections`). Report mode: the result (`valid`/`invalid`/`missing`/`no_secret`) is recorded, never refused, until the scheme is confirmed against real deliveries.
- Only events matching the bill-to rule are stored in `webhook_events`: the bill-to (or the body's `BillToID`) is onboarded and active, or the entity is one we already hold (deletes may lack a body). Employees always match: technicians are operator-wide. Note body fields (`LocationID`, `OrderID`) are assumed until a sample confirms them.
- Redeliveries (same operator, body hash, and timestamp) are stored once. The worker clears raw bodies after `WEBHOOK_RAW_RETENTION_DAYS` (30); the row stays. No object storage.
- Processing is a stub: events stay `received`. Planned handlers are listed in `app/services/webhooks.py`.

## Authorization (RBAC)

- Permissions decide what users can see and do, at both API and UI layers. Never check role names in routes or components.
- `app/security/permissions.py` is the source of truth for permission codes and system roles (`platform_admin`, `operator_admin`, `operator_staff`). `app.bootstrap` syncs the database to it; `tests/test_rbac.py` fails if the latest migration doesn't match. Changing a permission or system role needs a migration.
- A membership grants a role on a tenant and applies to that tenant and everything beneath it: platform memberships cover every operator.
- Each route declares its permission via `scope.require(perm, operator_id, read_perm=...)` or `require_any(perm)`. Return 404 when the caller can't see the resource at all (don't reveal other operators' records) and 403 when they can see it but lack the permission.
- Nobody may grant a role holding permissions they don't have on that tenant; the last platform admin can't be removed.
- New users are added with a temporary password and must change it before any other API call succeeds.
- Every endpoint must appear in `tests/test_access_matrix.py` with the expected status for each actor; a test fails when a `/v1` route is missing from it.
- UI: `usePermissions()` / `<Can>` in `web/src/lib/permissions.tsx` mirror the backend rule to hide or disable actions. They are not a security boundary.

## Authentication and Browser Security

- Login accepts email and password only. Emails are globally unique.
- Hash passwords with Argon2id; keep credentials separate from the user record.
- FastAPI mints signed JWT access and refresh tokens. Preserve refresh-token rotation, session records, revocation, and logout.
- Bootstrap the first platform administrator from environment settings with `python -m app.bootstrap`; keep it idempotent.
- Never commit `.env` files or credentials.

Next.js is a thin backend-for-frontend (BFF):

- The browser calls Next.js, not FastAPI.
- Next.js stores tokens in `HttpOnly`, `Secure`, `SameSite` cookies. Browser JavaScript never receives JWTs or stores them in `localStorage`/`sessionStorage`.
- Next.js forwards requests with the access token as a Bearer header and coordinates refresh.
- State-changing BFF endpoints have CSRF protection. Prefer same-origin deployment.
- Next.js may own route protection, redirects, forwarding, refresh coordination, and UI-specific aggregation. It must not access the database or duplicate authentication, authorization, or other domain rules.
- Backend authorization is final even when the UI hides or disables an action.

## Frontend Architecture

One application for all user types; separate experiences with route groups, not separate apps.

- React with strict TypeScript; Next.js App Router (no Vite or React Router)
- shadcn/ui and Tailwind CSS
- TanStack Query for server state
- React Hook Form and Zod for forms and validation
- Orval for the generated API client and models
- Lucide React for icons
- pnpm

## UI and Styling

- Brand: Select Exterminating. `docs/design-guidance.md` is the source; §9 "Application UI" defines how the brand maps to app tokens and overrides the marketing-site rules where they conflict (Forest, not Select Green, for buttons; 16px body; sentence-case inline actions). Map colors only through the semantic CSS variables in `web/src/app/globals.css`. Feature code uses semantic utilities such as `bg-primary`, `text-muted-foreground`, `bg-highlight`, never raw hex or palette classes like `bg-green-700`.
- Tokens are hex in `:root`; `pnpm lint` runs `pnpm check:contrast`, which fails if a token pair drops below WCAG 2.2 AA. Add a pair there when introducing a new foreground/background combination.
- Validate text, icon, focus, and interactive-state contrast against WCAG 2.2 AA. Accessibility overrides literal palette use.
- Keep shadcn primitives in `components/ui`; features compose them rather than modifying them.
- Use `class-variance-authority` and a shared `cn()` helper. No Sass, CSS-in-JS, or another styling framework without a specific need.

## Testing and Verification

Backend, for every change:

```text
pipenv run ruff check .
pipenv run pytest
pipenv run alembic check
```

Migration changes must be exercised through upgrade and downgrade **against a scratch database, never the development database** — a downgrade drops data. When a migration check targets a temporary database, verify `current_database()` before any downgrade, and call the virtualenv's `alembic` directly with an explicit `DATABASE_URL` — `pipenv run` loads `.env` and can redirect the command to the development database.

Frontend: `pnpm typecheck`, `pnpm lint` (includes `pnpm format:check` and the theme contrast check), `pnpm build`. Format with `pnpm format` (Prettier, 100 columns, Tailwind classes sorted); generated client and `components/ui` are excluded. Regenerate the API client (`pnpm api:generate`) whenever the backend contract changes. Test authorization on the backend; UI visibility checks are not a substitute.

## Local Development

```text
cp .env.example .env
pipenv install --dev
docker compose up -d postgres
pipenv run alembic upgrade head
pipenv run python -m app.bootstrap
pipenv run uvicorn app.main:app --reload --port 8001
pipenv run python -m app.worker          # separate terminal: background syncs
cd web && cp .env.example .env.local && pnpm install && pnpm dev
```

## Change Discipline

- Keep work focused on the current scope: tenants, RBAC, companies, and bill-to onboarding; PestPac webhook capture is stubbed (stored, not processed); its handlers are next. Don't build deferred features (customer logins, custom roles, regions, branches, theming, frontend test tooling) unless the user advances scope, but keep designs extensible for them.
- Add an Alembic migration for every persistent schema change.
- Preserve user changes and unrelated work already in the repository.
- Update this file when an architectural or product decision is explicitly changed.
