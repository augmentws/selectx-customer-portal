# Customer Portal

FastAPI backend + Next.js (App Router) BFF frontend. See `AGENTS.md` for the architecture rules.

| Service    | Port | Notes                                   |
| ---------- | ---- | --------------------------------------- |
| PostgreSQL | 5433 | `docker compose up -d postgres`         |
| FastAPI    | 8001 | docs at http://127.0.0.1:8001/docs      |
| Next.js    | 3001 | http://localhost:3001                   |

## Prerequisites

Python 3.14, Pipenv, Node 22+, pnpm, Docker.

## First run

```bash
cp .env.example .env              # then set JWT_SECRET and the BOOTSTRAP_ADMIN_* values
pipenv install --dev
docker compose up -d postgres
pipenv run alembic upgrade head
pipenv run python -m app.bootstrap  # creates the first admin; safe to re-run
pipenv run uvicorn app.main:app --reload --port 8001

cd web
cp .env.example .env.local
pnpm install
pnpm dev
```

Sign in at http://localhost:3001/login with the bootstrap admin (a platform admin), then add operators, companies, bill-tos, and members from the UI.

## Checks

```bash
pipenv run ruff check . && pipenv run pytest && pipenv run alembic check
cd web && pnpm typecheck && pnpm lint && pnpm build
```

After changing the API, regenerate the frontend client with the backend running:

```bash
cd web && pnpm api:generate
```

## Layout

```
app/                 FastAPI app (api/v1, models, schemas, services, security)
app/integrations/    PestPac API client
alembic/             migrations
tests/               pytest (uses the customer_portal_test database)
web/                 Next.js app; src/app/api/bff forwards to FastAPI
```
