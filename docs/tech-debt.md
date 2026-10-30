# Tech debt

Known gaps and shortcuts we've chosen to live with for now. Add an entry when you take one on;
remove it when it's paid off.

## Reports and findings

- **Report templates aren't loaded from the repo.** `docs/report-templates/` holds the reference
  copy of each template (HTML, fields, prompt), but the live template is whatever a platform admin
  last saved in the app. Changing the files changes nothing until someone pastes them into the
  template editor (or `PATCH /v1/report-templates/{id}`), so the two can drift.
- **Findings vocabularies are hard-coded.** The pest list (`Pest`), visit types, evidence, and the
  structural and sanitation categories are `Literal`s in `app/services/inspection_findings.py`, sent
  to the LLM as JSON-schema enums. Adding a value (e.g. `gnats`) needs a code change and deploy.
  Extract them from code (a table or per-operator config) so they can be maintained without one;
  stored values are plain strings, so existing rows don't need migrating.
- **Findings aren't exposed.** `inspection_findings` is written but no API route or page reads it
  yet; the dashboard and per-store baseline will be its first readers.

## Integrations

- **PestPac webhook signatures are only reported.** The HMAC result is recorded on each event but
  never enforced, until the scheme is confirmed against real deliveries. Until then webhook bodies
  are never written directly; they only queue syncs.
- **GoCanvas submissions aren't read from webhooks.** Requests are stored as received; submissions
  are loaded by hand with `python -m app.load_inspections`.

## Tooling

- **No CI.** The repository has no checks on pull requests; `ruff`, `pytest`, `alembic check`, and
  the frontend checks are run locally before merging.
