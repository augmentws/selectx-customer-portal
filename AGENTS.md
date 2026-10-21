# Customer Portal Repository Instructions

These decisions are authoritative for this repository until the user explicitly changes them. Preserve them when designing, implementing, or reviewing work, and update this file when a decision changes.

Bootstrap tier: standard

## Product and Scope

SELECTX customer portal: a web app where customers sign in to view their account and service information, backed by data from the PestPac (WorkWave) API.

This repository holds the backend API and the single web application:

- `app/`: FastAPI application and domain logic
- `app/integrations/pestpac/`: PestPac API client (OAuth2 password grant, per-resource sections). Only the backend calls PestPac; credentials come from `PESTPAC_*` env vars.
- `alembic/`: database migrations
- `tests/`: backend tests
- `web/`: Next.js application

## Backend Architecture

Use Python 3.14, FastAPI, SQLAlchemy, Alembic, Pipenv, PostgreSQL, and Docker Compose. The local database is named `customer_portal` (tests use `customer_portal_test`). Local ports: PostgreSQL 5433, FastAPI 8001, Next.js 3001.

FastAPI is the authority for domain behavior, authentication, authorization, sessions, and auditing. Do not move domain logic into the UI or its proxy layer.

The OpenAPI document at `/openapi.json` is the API contract. Interactive docs are at `/docs`. The frontend's TypeScript types and client are generated from it with Orval; never hand-edit generated output.

Current API surface (keep the versioned shape unless a contract change is requested):

- `GET /health`
- `POST /v1/auth/login`, `POST /v1/auth/refresh`, `POST /v1/auth/logout`, `GET /v1/auth/me`
- `GET /v1/items`, `POST /v1/items`, `GET /v1/items/{item_id}` (sample resource; authenticated)

## Authentication and Browser Security

- Login accepts email and password only. Emails are globally unique.
- Hash passwords with Argon2id; keep credentials separate from the user record.
- FastAPI mints signed JWT access and refresh tokens. Preserve refresh-token rotation, session records, revocation, and logout.
- Bootstrap the first administrator from environment settings with `python -m app.bootstrap`; keep it idempotent.
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

- Brand palette: neutral placeholder. Map palette colors to semantic CSS variables (background, foreground, card, muted, primary, secondary, accent, destructive, border, input, ring, plus state tokens). Feature code uses semantic utilities such as `bg-background` and `text-muted-foreground`, never raw palette classes like `bg-blue-600`.
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

Migration changes must be exercised through upgrade and downgrade. When a migration check targets a temporary database, verify `current_database()` before any downgrade, and call the virtualenv's `alembic` directly with an explicit `DATABASE_URL` — `pipenv run` loads `.env` and can redirect the command to the development database.

Frontend: `pnpm typecheck`, `pnpm lint`, `pnpm build`. Regenerate the API client (`pnpm api:generate`) whenever the backend contract changes. Test authorization on the backend; UI visibility checks are not a substitute.

## Local Development

```text
cp .env.example .env
pipenv install --dev
docker compose up -d postgres
pipenv run alembic upgrade head
pipenv run python -m app.bootstrap
pipenv run uvicorn app.main:app --reload --port 8001
cd web && cp .env.example .env.local && pnpm install && pnpm dev
```

## Change Discipline

- Keep work focused on the current scope: auth shell, sample `items` resource, and the PestPac client. Don't build deferred features (customer-facing PestPac views, roles beyond admin, theming, frontend test tooling) unless the user advances scope, but keep designs extensible for them.
- Add an Alembic migration for every persistent schema change.
- Preserve user changes and unrelated work already in the repository.
- Update this file when an architectural or product decision is explicitly changed.
