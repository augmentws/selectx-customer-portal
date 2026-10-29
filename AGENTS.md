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

Use Python 3.14, FastAPI, SQLAlchemy, Alembic, Pipenv, PostgreSQL, and Docker Compose. PDF reports use Jinja2 and WeasyPrint (system dependency: Pango). The local database is named `customer_portal` (tests use `customer_portal_test`). Local ports: PostgreSQL 5433, FastAPI 8001, Next.js 3001, MinIO 9000 (S3 API) and 9001 (console).

Object storage is any S3-compatible service, reached only through the S3 API (no MinIO-specific SDK or features), so MinIO locally and R2 or S3 elsewhere are interchangeable. Locally it's MinIO (AIStor) in Docker Compose; its license (`minio.license`) and data directory (`.data/`) are gitignored. Document files are the only thing stored so far. The app uses its own MinIO user and bucket, not the root credentials.

FastAPI is the authority for domain behavior, authentication, authorization, sessions, and auditing. Do not move domain logic into the UI or its proxy layer.

The OpenAPI document at `/openapi.json` is the API contract. Interactive docs are at `/docs`. The frontend's TypeScript types and client are generated from it with Orval; never hand-edit generated output.

Current API surface (keep the versioned shape unless a contract change is requested):

- `GET /health`
- Auth: `POST /v1/auth/login`, `/refresh`, `/logout`, `/password`; `GET /v1/auth/me` (includes memberships, company memberships, and permissions)
- `GET/POST /v1/operators`, `GET/PATCH /v1/operators/{id}`, `GET/POST /v1/operators/{id}/companies`
- `GET/PATCH /v1/companies/{id}`, `GET/POST /v1/companies/{id}/bill-tos`, `GET /v1/companies/{id}/locations`, `GET /v1/companies/{id}/posted-service-orders`, `GET /v1/companies/{id}/open-service-orders`
- `GET/PATCH /v1/bill-tos/{id}`, `POST /v1/bill-tos/{id}/refresh`, `GET /v1/bill-tos/{id}/locations`, `GET /v1/bill-tos/{id}/service-orders`, `GET /v1/bill-tos/{id}/posted-service-orders`, `GET /v1/bill-tos/{id}/open-service-orders`, `POST /v1/bill-tos/{id}/service-orders/sync`, `GET /v1/bill-tos/{id}/sync-jobs`
- `GET /v1/locations/{id}`, `GET /v1/locations/{id}/notes`, `GET /v1/locations/{id}/service-orders`, `GET /v1/locations/{id}/posted-service-orders`, `GET /v1/locations/{id}/invoiced-service-orders` (`billing:read`), `GET /v1/locations/{id}/open-service-orders`, `POST /v1/locations/{id}/service-orders/sync`
- Invoices (`billing:read`): `GET /v1/locations/{id}/invoices` (`limit`/`offset`), `GET /v1/invoices/{id}`, `GET /v1/bill-tos/{id}/invoiced-orders`, `GET /v1/companies/{id}/invoiced-orders` (each invoice with its service order)
- Documents and conditions: `GET /v1/locations/{id}/documents`, `GET /v1/locations/{id}/conditions`, `GET /v1/documents/{id}/file`
- "Sync location": `POST /v1/locations/{id}/sync`, `POST /v1/bill-tos/{id}/locations/sync`
- `GET /v1/service-orders/{id}` (with its trail, location name, report, and stored invoice id), `GET /v1/service-orders/{id}/notes`, `GET /v1/service-orders/{id}/related`, `GET /v1/sync-jobs/{id}`
- `POST /v1/webhooks/pestpac` (public; PestPac webhook deliveries)
- `POST /v1/webhooks/gocanvas/{operator_id}` (public; also GET/PUT, not in the schema), `GET /v1/operators/{id}/gocanvas-requests`, `GET /v1/gocanvas-requests/{id}`
- `GET /v1/operators/{id}/webhook-events` (filters incl. `entity_id`, `limit`/`offset`), `GET /v1/webhook-events/{id}` (with raw body)
- `GET /v1/companies/{id}/bill-tos/lookup`
- `GET /v1/search?q=` (header search; see Authorization)
- `GET/PUT /v1/operators/{id}/pestpac-connection`, `POST /v1/operators/{id}/pestpac-connection/verify`
- `GET/POST /v1/tenants/{id}/members`, `PATCH/DELETE /v1/tenants/{id}/members/{user_id}`
- Company users: `GET/POST /v1/companies/{id}/members`, `PATCH/DELETE /v1/companies/{id}/members/{user_id}`
- `GET /v1/roles`, `GET /v1/permissions`
- Dashboard: `GET /v1/companies/{id}/dashboard?bill_to_id=`
- Reports: `GET/POST /v1/companies/{id}/report-templates`, `GET/PATCH /v1/report-templates/{id}`, `GET /v1/locations/{id}/reports/{template_id}` (PDF), `POST /v1/locations/{id}/report-preview` (PDF)
- Service reports: `GET/POST /v1/locations/{id}/service-reports`, `GET/PATCH /v1/service-reports/{id}`, `POST /v1/service-reports/{id}/draft`, `GET /v1/service-reports/{id}/preview` (HTML), `POST /v1/service-reports/{id}/finalize`, `POST /v1/service-reports/{id}/revise`, `GET /v1/service-reports/{id}/pdf`

## Tenancy and Data Model

- `tenants` is a tree: exactly one `platform` root (SELECTX, the application admin) with `operator` tenants beneath it. Each operator maps 1:1 to a PestPac tenant (`pestpac_tenant_id`).
- `companies` are our own customer entity (PestPac has none) and belong to one operator.
- `bill_tos` are PestPac bill-tos onboarded to a company. Onboarding happens at the bill-to level; a bill-to may bill a single location, a region, or a whole company (recorded in `description`). `(operator_id, pestpac_bill_to_id)` is unique, and a composite FK keeps a bill-to inside its company's operator.
- Deactivate with `is_active`; don't hard-delete tenants, companies, or bill-tos.
- Every operator-owned row carries `operator_id`; queries are scoped through the services layer.
- Customer logins are company users: `company_memberships` grants a company-scoped role on one company (see Authorization). Only `company_manager` exists so far, and it sees the company's dashboard only.
- Not built yet (keep designs extensible): customer access beyond the dashboard, branches, regions, per-operator custom roles.

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
- Locations are read with `bill_tos:read` via `GET /v1/bill-tos/{id}/locations`, or across all a company's bill-tos via `GET /v1/companies/{id}/locations` (same shape and counts; the company page's Locations tab, which names each row's bill-to when the company has more than one). A company's bill-to cards link to their bill-to pages by title.

## Service Orders, Technicians, and Notes

- PestPac lists only *open* service orders, per location (`GET /Locations/{id}/serviceOrders`, not paged). `service_orders` is our permanent copy, keyed by `(operator_id, OrderID)`: open (`posted` false) → worked (`Posted` flips true; `posted_at` records when we first saw it) → billed (PestPac stops listing it; `closed_at`). Never delete service orders. Only orders whose BillToID is an onboarded, active bill-to are stored.
- Stored order fields: OrderID, OrderNumber, ServiceCode, Description, WorkDate (PestPac local wall-clock time, no timezone), Tech1, TechID1, Location/Service/Order instructions, TechnicianComment, Posted, and the InvoiceID learned from the order's notes. No pricing, tax, scheduling windows, or user-defined fields.
- Syncs run in the background worker, `python -m app.worker` (`--once` to drain the queue). `sync_jobs` are claimed with `FOR UPDATE SKIP LOCKED`; stale running jobs are retried up to `SYNC_JOB_MAX_ATTEMPTS`. Each location commits on its own; jobs end `succeeded`, `partial`, or `failed`. Onboarding a bill-to queues its first sync.
- `SYNC_ACTIVE=false` (default true) pauses syncing with PestPac: webhooks are still captured, but the worker neither handles webhook events nor runs sync jobs (they wait, and run once it's true again; report drafts still run), and the four sync endpoints answer 409. One-off calls people make (saving or verifying credentials, bill-to lookup, onboarding, refresh) still reach PestPac.
- Each job first seeds technicians from `GET /lookups/Employees/technicians` (not paged; not fatal on failure); `GET /lookups/Employees/technicians/{techId}` is the per-job, once-per-tech fallback. A technician problem never fails an order. Store only TechID, EmployeeID, username, first/last name, and Active.
- Notes: one `notes` row per NoteID, mirroring PestPac (a note can be associated with several objects). Objects we model get real foreign keys (`location_id`, `bill_to_id`, `service_order_id`, `created_by_technician_id`); every association is also kept as its raw PestPac id. Don't create per-object note tables.
- Each location's full note history is synced: `GET /Locations/{id}/notes` (paged with `skip`/`top`; it ignores `take`, unlike the `/pageable` endpoints), then `GET /Notes/{id}` once per new note for its associations. Known notes are refreshed from the list without a detail call. Posted orders without an InvoiceID have their notes' associations re-checked on later syncs. Notes are synced after the location's orders commit; a notes failure never undoes them.
- Pages: a location's page is tabbed (Overview with details, both syncs, and reports; Service orders; Conditions; Documents, 25 at a time; Invoices with `billing:read`; Notes). A bill-to's locations are a sortable table, 50 rows a page, from `GET /v1/bill-tos/{id}/locations`, whose items carry `open_order_count` (unbilled, worked or not), `worked_order_count`, and `last_service_at` (WorkDate of the latest worked order). The UI calls the two syncs "Orders and notes" and "Documents and conditions" ("Sync location" in the API).
- Lists: a location's Service orders tab has sub-tabs (`?orders=`) like the customer page: Posted, Invoiced (`billing:read`; the orders only, not their invoices), and Open, each with the posted list's filters, sort, and paging. Orders that drop off PestPac without being worked appear in none of them. Bill-to order lists (`/service-orders`) are newest first. "Posted service orders" (bill-to and company tabs) lists worked orders without a stored invoice, oldest first, paged with `limit`/`offset`, each with its `report_id` (Start report / Open report there). Filters: `q` (order number or OrderID exactly, or the location's name, which carries the store number, anywhere), `technician_id`, `service_code`; the page also returns `technicians` and `service_codes` over all its posted orders, for the filter choices. `sort=desc` lists them newest first. "Open orders" (same pages, after Invoiced orders; `bill_tos:read`) lists orders not worked yet that PestPac still lists, with the same filters and sort and no report action. The UI keeps the filters in the URL, each tab under its own parameters. "Invoiced orders" (same pages, `billing:read`) lists invoices newest first by invoice date (`sort=asc` for oldest first), each with the order it bills.
- `CreatedByUser` links to a technician by username when there is one; otherwise it stays a raw username.
- Service order page (`/service-orders/{id}`, opened from "Order N" in every order list and from search): details, instructions, then what was logged around it from `GET /v1/service-orders/{id}/related` (`app/services/order_related.py`): documents (linked by our FK or PestPac's OrderID; condition documents sit under their conditions), conditions (opened or inspected on the order, with inspections and photos), and notes. PestPac links few items to orders, so the location's items within a day of the work date (the service reports' window) are included too, marked `same_day`; linked items first. With `billing:read`, the stored invoice. Order rows keep their instructions-and-notes fold-out.
- PestPac calls have timeouts. Request/response bodies contain customer data and are logged only when `PESTPAC_DEBUG_BODIES=true` (local debugging).
- Tests mock PestPac with `responses` (`pestpac` fixture in `tests/conftest.py`); they must never call the real API.

## Invoices (billing)

- Invoices are the one place we keep money: an explicit exception to "no pricing, tax, or balances" elsewhere. `invoices` (one per InvoiceID per operator; FKs to bill-to, location, service order, and technician; raw ids kept) and `invoice_lines` (replaced on every fetch). Whitelisted in `PestPacInvoiceDetails`: InvoiceID, LocationID, BillToID, SetupID, OrderID, InvoiceNumber, OrderNumber, ServiceCode, Description, Total, Balance, ServiceFeeTotal, Cost, Invoice/Work/Due/Order dates (PestPac wall-clock time), TimeRange, Duration, InvoiceType, OrderType, Origin, Location/Service/Order instructions, TechnicianComment, BatchNumber, and LineItems (code, description, cost, unit price, quantity, extended price, taxable, GL code). Never kept: tax details, contact names (ServiceLocation/BillTo), branch, terms, user-defined fields, the raw response, and technicians beyond position 1 or any technician pay (Commission, Bonus, Share). The position-1 TechID links to `technicians`.
- Only invoices whose BillToID is an onboarded, active bill-to are stored. Never deleted: a delete webhook or a 404 sets `removed_at`.
- Two ways in: invoice webhooks (any action captured; create then updates arrive seconds apart) make the worker fetch `GET /Invoices/{id}` once per batch: an invoice's events wait `INVOICE_WEBHOOK_WAIT_MINUTES` (5) after its first one, or until `INVOICE_WEBHOOK_MAX_UPDATES` (3) updates arrive, then share one fetch, skipped when our copy was fetched after they arrived; deletes are handled at once, with no call. And every order sync, after notes, covers the location's worked (posted) orders that have no stored invoice: one we already hold for the OrderID (stored before we held the order) is linked with no call; otherwise it searches `GET /Invoices?orderNumber=` (unbilled ones find nothing and are retried next sync; a failure makes the job `partial` but never undoes orders or notes). The search answers with the full invoice object (same shape as `GET /Invoices/{id}`, confirmed); only an exact OrderNumber match is kept. 404 means not invoiced yet (confirmed); any other answer that isn't an invoice fails the location's invoice step.
- An order we never saw (billed before we heard of it) is created from its invoice when its invoice webhook is handled: worked and billed, Tech1's username unknown; the order's notes are then linked. Order webhooks never search invoices. Failed invoice events whose invoice still isn't stored are sent back through the handler by `python -m app.worker --requeue-failed-invoices`.
- An invoice completes its order, without overwriting: sets `pestpac_invoice_id`, marks it worked if we never saw it posted, and fills an empty `technician_comment`.
- Seen only with `billing:read` (platform and operator admins; not staff).

## Documents

- One `documents` table for every PestPac document, keyed by `(operator_id, document_type, DocumentID)` (ids may repeat across types). Like notes, modelled objects get foreign keys (`location_id`, `service_order_id`) and raw PestPac ids are kept. Whitelisted fields only: type, name, file name, date (PestPac wall-clock time), effective dates, tech-photo flag, `IncludeOn` flags (snake_cased; `portal` is PestPac's customer-visible flag), OrderID, SetupID. PestPac's `URL` is empty and isn't kept. Some names are garbled in PestPac itself (UTF-8 read as Windows-1252 before upload, e.g. "â€”" for "—"; PestPac sends them correctly encoded, confirmed), so `Name` and `FileName` go through `repair_mojibake` on the way in: repaired only when the telltale pattern is there and the whole name converts cleanly.
- Synced by "Sync location" (`location_sync` / `bill_to_location_sync` jobs in the worker), on request; order syncs fetch conditions (below) but never document lists or files. It's the home for per-location syncs beyond orders and notes; add new ones there. Per location: `GET /Locations/{id}/documents?startDate={PESTPAC_DOCUMENTS_START_DATE}&includeConditionDocuments=true` (one unpaged array), then `GET /Documents/{id}/download?type={DocumentType}` for each file not stored yet. Files are fetched once.
- Files go to object storage under `operators/{operator}/documents/{type}/{DocumentID}` (never the file name), through `app/storage.py` (S3 API only). Each stored file commits on its own. A file's own problem (error status, JSON instead of a file, over `DOCUMENT_MAX_BYTES`) is recorded in `file_error` and doesn't fail the location; too-large files aren't downloaded again. PestPac's API gateway (Apigee) refuses files over 10 MB with a 502 fault `protocol.http.TooBigBody` (confirmed): those get `file_unavailable` and are never tried again (the row stays; open them in PestPac). Other errors are retried each sync. The Documents tab marks any file that failed with a "File failed" badge and the reason. PestPac or storage being unreachable fails the location. Without `S3_BUCKET`, lists still sync and files wait.
- Documents PestPac stops listing get `removed_at` (only those dated from the start date, since older ones aren't listed). Rows and files are never deleted.
- Files are served by FastAPI with `bill_tos:read`: images and PDFs inline, everything else as an attachment, always with `nosniff`, and with `Content-Security-Policy: sandbox` on everything but PDFs (Chrome's PDF viewer refuses to load sandboxed: ERR_BLOCKED_BY_CLIENT), so a PestPac file can't run script on our origin. The BFF forwards those headers.
- Downloads return the raw file with its content type (confirmed against PestPac: PDF, JPEG, PNG, MP4); a JSON body is treated as a failure, not stored.
- Tests use the in-memory store from the autouse `storage` fixture; `S3_BUCKET` is cleared so they never reach a real store.

## Conditions (issues)

- `conditions` (one per IssueID per operator; FKs to location and service order, raw ids kept) and `condition_inspections`. PestPac gives inspections no id, so a condition's inspections are replaced whenever its details are fetched. Fields are whitelisted in `PestPacConditionSummary` / `PestPacConditionDetails` (StationID isn't kept); dates are PestPac wall-clock time.
- "Sync location" runs, per location: documents list, then `GET /Locations/{id}/conditions` (summaries; no status filter, so closed conditions and their history come too), then `GET /Conditions/{id}` only for new conditions or when `LastInspectedDate` or status changed, then files. Conditions we hold as Open that drop off the list are fetched once more to record the closing; a 404 marks them `removed_at`. Never deleted.
- A condition's `Documents` go into `documents` as usual (linked by `condition_id`, raw `pestpac_issue_id`); new ones get their files in the same run. The location documents list never marks a condition's documents removed.
- The location's documents and conditions lists commit together; a failure rolls both back for that location only.
- Order syncs (every "Orders and notes" sync, including those queued by order webhooks) also sync the location's conditions, after invoices, since a posted order is when a technician's new conditions appear. Their documents are stored as rows; files wait for "Sync location". A conditions failure makes the job `partial` and never undoes orders, notes, or invoices.

## PestPac Webhooks

- `POST /v1/webhooks/pestpac` is public (no session); the only route exempt from the access matrix besides auth. It answers 200 whether an event was stored, dropped, or a redelivery, so callers can't probe which bill-tos are onboarded; 400 for a malformed envelope, 413 above `WEBHOOK_MAX_BODY_BYTES` (read in chunks and cut off at the limit, declared or not).
- Envelope: `TenantId` (matched to `pestpac_tenant_id`), `EntityType`, `EntityId`, `Action`, `EntityBody`. Captured: Bill-To, Employee, Location, Note (create/update/delete), Service Order (create/update/post/delete), and Invoice (any action); everything else is dropped.
- Signature: HMAC-SHA256 of the serialized `EntityBody` plus the `timestamputc` header, in `signature` headers, keyed by the operator's optional, write-only webhook secret (encrypted on `pestpac_connections`). Report mode: the result (`valid`/`invalid`/`missing`/`no_secret`) is recorded, never refused, until the scheme is confirmed against real deliveries.
- Only events matching the bill-to rule are stored in `webhook_events`: the bill-to (or the body's `BillToID`) is onboarded and active, or the entity is one we already hold (deletes may lack a body). Employees always match: technicians are operator-wide. Note body fields (`LocationID`, `OrderID`) are assumed until a sample confirms them.
- Redeliveries (same operator, body hash, and timestamp) are stored once. The worker clears raw bodies after `WEBHOOK_RAW_RETENTION_DAYS` (30); the row stays. No object storage.
- Invoice events are captured with any action and handled as described under Invoices.
- The worker processes stored events (`app/services/webhook_handlers.py`, oldest first, `SKIP LOCKED`). Service orders and invoices have handlers. Service orders: create/update/post queue the usual sync of the order's location (the body's LocationID, else our copy's location; a location we haven't synced queues the bill-to sync instead). The body is never written directly while signatures are only reported. Events share a job already queued or running for that location; `sync_job_id` records it. A billed order is gone from PestPac (only its invoice remains), so the sync can't see it: it arrives through its invoice event instead (see Invoices). Delete and inactive bill-tos: `processed` with no sync. No target, or a handler bug: `failed` with the reason. Other entities stay `received`; their planned handlers are listed in `app/services/webhooks.py`.
- Stored events are viewable with `webhooks:read` (platform and operator admins; bodies hold customer data) on the operator page's Webhooks tab. Dropped deliveries are never stored, so they can't be shown.

## GoCanvas Webhooks

- Each operator has its own public URL, `POST /v1/webhooks/gocanvas/{operator_id}` (GET and PUT are accepted too). Every request is stored in `gocanvas_requests` as received, since GoCanvas's format isn't known yet: method, query string, content type, headers minus credentials (Authorization, Cookie, API-key headers), body (UTF-8, undecodable bytes replaced; capped by `WEBHOOK_MAX_BODY_BYTES`, 413 above it), size and SHA-256, sender IP and user agent. Nothing is processed.
- Answers 200 always; requests for an unknown or inactive operator aren't stored, so the URL can't probe operators. Raw bodies are cleared by the worker after `WEBHOOK_RAW_RETENTION_DAYS`; rows stay.
- Viewable with `webhooks:read` on the operator page's GoCanvas tab.

## Webhook senders

- Both receivers record who sent each stored request: `client_ip` (the connecting address: a proxy's when one is in front), `forwarded_for` (X-Forwarded-For as sent, unverified; don't treat it as the sender), and `user_agent`. PestPac deliveries dropped by the bill-to rule aren't stored, so they aren't recorded either.

## LLM Data Clean-up (OpenRouter)

- `app/integrations/openrouter/` wraps OpenRouter's chat completions (`POST {OPENROUTER_BASE_URL}/chat/completions`). One platform-wide key, `OPENROUTER_API_KEY`, from settings; never per operator, never committed. Only the backend calls it.
- Models are OpenRouter ids chosen per task or call, falling back to `OPENROUTER_DEFAULT_MODEL`; there is no hard-coded default model.
- Clean-up work is an `LLMTask` (instructions + Pydantic output model) run with `app.services.llm_tasks.run_task`: JSON-schema `response_format`, routed only to providers that support it (`provider.require_parameters`), validated, one retry with the validation errors. Results carry the serving model and token/cost usage.
- The client retries 408/429/502/503 and network errors with backoff, and treats an `error` in a 200 body as a failure. Prompts and completions are logged only with `OPENROUTER_DEBUG_BODIES=true`.
- Tests mock OpenRouter with `responses`; they never call the real API.
- Stub: nothing calls these yet (`ADDRESS_CLEANUP` is the example task). Wire tasks into the worker, not request handlers, so slow model calls don't block requests.

## PDF Reports

- `report_templates` are per company (any number), HTML with inline CSS, written only by platform admins (`report_templates:write`); every system role has `reports:read` to list them and generate PDFs. Deactivate with `is_active`; `version` increments when the HTML, fields, or prompt change. The one-click location PDF is not stored or logged; service reports (below) are. Templates with `fields` are service report templates: they aren't offered as one-click PDFs (409).
- Templates are Jinja rendered by `app/services/reports.py` in a `SandboxedEnvironment` with autoescaping and `StrictUndefined`. Saving test-renders against `sample_context()`; render errors are 422 with the Jinja message.
- Templates see only `ReportContext` in `app/schemas/reports.py` (operator, company, bill-to, location, `generated_at` in UTC), passed as plain dicts. To expose more data, add fields there and in `build_context`; never pass ORM objects to templates.
- WeasyPrint renders the PDF with a URL fetcher limited to `data:` URIs: images, fonts, and stylesheets must be embedded, and nothing is fetched over the network or from disk. It needs Pango installed on the host.
- A location only renders its own company's active templates (404 otherwise).
- Templates can declare `fields` (`TemplateField`: key, label, type `text`/`paragraphs`/`list`/`sections`, `llm`, `help`, `default`), a drafting `prompt`, and an optional `llm_model`. The HTML reads `fields.<key>`; text is rendered with the `rich` filter, which escapes it and allows only `**bold**`. Saving test-renders with sample values for every field, so the HTML and fields must agree. A template, its fields, and its prompt work together; keep them in one place (the rodent-control one is in `docs/report-templates/`).

## Service Reports

- Versions: "New version" (revise) copies the order's latest version into a new draft revision; only the latest version can be revised, so there's at most one draft. Finalizing a version marks the order's earlier final versions `superseded` (PDF kept, read-only): only the newest version is final.
- One report per service order, whatever the template (starting a second is 409; changes are revisions): `reports` stores the data that goes into the PDF (`data`: a context snapshot taken when started, field values, candidate notes and photos with selections and captions), separately from the PDF itself (object storage, `operators/{op}/reports/{id}/r{n}.pdf`, with size and SHA-256 on the row). Never deleted.
- Started from an order's row (`reports:write`: platform and operator admins): a location's Service orders tab, or a bill-to's or company's posted orders. The location's Overview lists its reports. Notes and images are linked by date, since PestPac rarely links them to an order: those within a day of the WorkDate are offered; on the work date (or note linked to the order) start selected.
- The order's TechnicianComment is snapshotted into `data.technician_comment` when the report is started (selected by default) and offered as its own checkbox; drafting needs a selected note or the comment.
- "Draft narrative" queues the worker, which sends the selected notes and technician comment (plus location and order) to the LLM via `run_task` with the template's prompt plus a generated description of its `llm` fields; the structured reply fills those fields. LLM failures are recorded on the report (`draft_error`), never raised. No model is configured yet: set `OPENROUTER_API_KEY` and a model (template or `OPENROUTER_DEFAULT_MODEL`).
- Editing and previewing (HTML from the saved data, shown in a sandboxed iframe) are allowed while `draft`. Finalizing renders the PDF from the saved data, stores it, and locks the report; changes after that are a new revision copying the data. Photos are downscaled with Pillow (a WeasyPrint dependency) and embedded as `data:` URIs at render time; they're referenced, not copied, in `data`. The BFF forwards `content-disposition`; the web app fetches PDFs with `web/src/lib/api/pdf.ts`, since the generated client reads bodies as text.

## Program Dashboard

- Plan: `docs/customer-dashboard-plan.md` (billing is separate: `docs/billing-dashboard-plan.md`). The current dashboard is a stub for Select staff (`dashboards:read`, all system roles) showing service activity only; findings, programs, and risk tabs are labelled placeholders naming the plan phase that fills them.
- `app/services/dashboard.py` aggregates in SQL and returns summaries, never raw order rows. A "service" is a worked (`posted`) order dated by WorkDate; worked orders PestPac no longer lists count as billed.
- Charts use the shadcn chart component (Recharts) with semantic `--chart-*` tokens; every chart has a table view, single-series charts use `--chart-1`.

## Authorization (RBAC)

- Permissions decide what users can see and do, at both API and UI layers. Never check role names in routes or components.
- `app/security/permissions.py` is the source of truth for permission codes and system roles (`platform_admin`, `operator_admin`, `operator_staff`). `app.bootstrap` syncs the database to it; `tests/test_rbac.py` fails if the latest migration doesn't match. Changing a permission or system role needs a migration.
- A membership grants a role on a tenant and applies to that tenant and everything beneath it: platform memberships cover every operator.
- Each route declares its permission via `scope.require(perm, operator_id, read_perm=...)` or `require_any(perm)`. Return 404 when the caller can't see the resource at all (don't reveal other operators' records) and 403 when they can see it but lack the permission.
- Nobody may grant a role holding permissions they don't have on that tenant; the last platform admin can't be removed.
- Company users (a customer's people) hold a company-scoped role (`RoleScope.company`; `company_manager`: `companies:read`, `dashboards:read`) in `company_memberships`, kept apart from `memberships` so a company grant is never read as an operator grant. A grant counts only where a route passes `company_id` to `scope.require` (today `GET /v1/companies/{id}` and its dashboard); every other route checks the operator, so company users get 404 there and 403 on routes open to anyone who sees an operator. Grants on an inactive company or operator count for nothing. They're managed on the company page's Members tab with the operator's `members:read`/`members:write`. In the UI, a user with only company grants lands on their company's dashboard, which hides the bill-to filter, store links, and breadcrumbs from them; the company page sends them there.
- New users are added with a temporary password and must change it before any other API call succeeds.
- Every endpoint must appear in `tests/test_access_matrix.py` with the expected status for each actor; a test fails when a `/v1` route is missing from it.
- Search (`GET /v1/search`, `app/services/search.py`) returns each kind only from operators where the caller holds the permission its page needs (operators and companies: their read permission; bill-tos, locations, and orders: `bill_tos:read`; invoices: `billing:read`), so a hit never leads to a 404. Names match anywhere (LIKE wildcards escaped); PestPac ids and order/invoice numbers match exactly. Orders and invoices open on their location's page.
- UI: `usePermissions()` / `<Can>` in `web/src/lib/permissions.tsx` mirror the backend rule to hide or disable actions. They are not a security boundary.

## Authentication and Browser Security

- Login accepts email and password only. Emails are globally unique.
- Hash passwords with Argon2id; keep credentials separate from the user record.
- FastAPI mints signed JWT access and refresh tokens. Preserve refresh-token rotation, session records, revocation, and logout. A refresh for a deactivated user revokes the session. `JWT_SECRET` must be at least 32 characters and not the `.env.example` placeholder (startup fails otherwise); settings errors never echo values.
- Sign-in lockout: `LOGIN_MAX_FAILURES` (5) failures for one email within `LOGIN_FAILURE_WINDOW_MINUTES` (15) lock it for `LOGIN_LOCK_MINUTES` (15): 429 with `Retry-After`, the password not checked. Counted per normalized email in `login_throttles` whether or not an account exists, so a lockout reveals nothing; a successful sign-in clears it. Login passwords are capped at 256 characters (each attempt is an Argon2 hash).
- Bootstrap the first platform administrator from environment settings with `python -m app.bootstrap`; keep it idempotent.
- Never commit `.env` files or credentials.

Next.js is a thin backend-for-frontend (BFF):

- The browser calls Next.js, not FastAPI.
- Next.js stores tokens in `HttpOnly`, `Secure`, `SameSite` cookies (`Secure` in production and whenever the request came over HTTPS, including through a tunnel). Browser JavaScript never receives JWTs or stores them in `localStorage`/`sessionStorage`.
- The BFF proxy forwards no `/v1/auth/*` route except `me` and `password` (trailing slashes ignored), and never follows FastAPI redirects.
- `next.config.ts` sets X-Frame-Options (SAMEORIGIN), Referrer-Policy, nosniff, Permissions-Policy, and HSTS on every response, and no X-Powered-By. Not a global Content-Security-Policy: document files carry their own (`sandbox`).
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
- "Add" forms (operator, company, bill-to onboarding) open from a header button in a dialog (`AddDialog`), not as cards above the lists.
- Detail pages (company, bill-to, location, service report) return a `trail` of their parents (operator › company › bill-to › location) from FastAPI; pages show it with `Breadcrumbs`, not hand-built back links. Pages beneath a company build theirs from the company's trail. Each page names the browser tab with `useDocumentTitle`.
- "Home" is `useHomeHref()`: the operators list, or the operator itself for someone who sees one operator and can't add operators.
- Tabs and badges follow `docs/design-guidance.md` §9: import tabs from `@/components/page-tabs` (brand line style), and pick badge variants by meaning (`pending`, `success`, `warning`, `destructive`, `outline`; never the filled button colours).
- Tabs keep their selection in the URL with `useUrlTab` (`web/src/lib/use-url-tab.ts`): `?tab=` by default, another parameter for tabs nested in a page. Switching pushes history, so Back and links return to the tab.
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
mkdir -p .data/minio && docker compose up -d minio   # needs ./minio.license
pipenv run alembic upgrade head
pipenv run python -m app.bootstrap
pipenv run uvicorn app.main:app --reload --port 8001
pipenv run python -m app.worker          # separate terminal: background syncs
cd web && cp .env.example .env.local && pnpm install && pnpm dev
```

## Change Discipline

- Keep work focused on the current scope: tenants, RBAC, companies, and bill-to onboarding; PestPac webhooks are stored; service orders are processed (queue a location sync), the other entities' handlers are next. Don't build deferred features (customer access beyond the dashboard, custom roles, regions, branches, theming, frontend test tooling) unless the user advances scope, but keep designs extensible for them.
- Add an Alembic migration for every persistent schema change.
- Preserve user changes and unrelated work already in the repository.
- Update this file when an architectural or product decision is explicitly changed.
