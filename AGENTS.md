# AGENTS.md

Guidance for AI coding agents working in this repository. Humans: start at
[README.md](README.md).

## What this is

A personal unwanted-call blocker: a Python backend (`backend/`) that keeps a public phone
directory imported from Polish registers plus user spam reports, and serves it to a planned
iPhone app through a JSON API. One user, one server. The iPhone app does not exist yet.

## Map

| Path | What |
|---|---|
| `backend/src/phone_blocker/` | Application package (see `backend/AGENTS.md` for module ownership) |
| `backend/tests/` | pytest suite; `tests/fixtures/` holds real register samples |
| `backend/compose.yaml`, `backend/Dockerfile` | Production stack (PostgreSQL, API, importer, backups, Caddy) |
| `.github/workflows/backend.yml` | CI: tests on SQLite and PostgreSQL, Docker image smoke test |
| `docs/` | Human documentation: architecture, API, data sources, operations, development, glossary |

## Commands (run in `backend/`)

```sh
uv sync                                  # install
uv run pytest -q                         # all tests, SQLite (~6 s); must pass before you finish
uv run phone-blocker migrate             # apply migrations to DATABASE_URL (default ./phone_blocker.db)
uv run phone-blocker import <source>     # uke bip nfz rpwdl apteki ceidg | all
uv run uvicorn phone_blocker.api:create_app --factory --port 8000
uvx pyflakes src tests                   # unused imports and similar
```

PostgreSQL run of the suite (do this for changes to models, migrations or SQL):
`docker run -d --rm --name pgtest -e POSTGRES_PASSWORD=pw -p 55432:5432 postgres:17-alpine`, then
`TEST_DATABASE_URL=postgresql+psycopg://postgres:pw@127.0.0.1:55432/postgres uv run pytest -q`.

## Rules

1. **Do not touch secrets.** Never print, commit or invent values for `API_TOKEN`,
   `POSTGRES_PASSWORD`, `CEIDG_TOKEN`, `NTFY_TOKEN` or the contents of `backend/.env`.
   `.env` is git-ignored; `.env.example` holds empty placeholders only.
2. **Schema changes need a migration.** Edit `models.py`, then generate with Alembic
   (see `docs/development.md#schema-changes`). `test_migrations_match_models` fails otherwise.
   Never edit a migration that has been pushed; add a new one.
3. **Caller-ID state is derived.** Only `directory.refresh_number` sets
   `PhoneNumber.label`, `.blocked` and `.version`. Any code that changes listings, reports or
   personal settings must call it for every affected number.
4. **Sources do not touch the database.** A source module fetches and parses and yields
   `(source_id, OrganizationRecord | None)`; the importer saves. Snapshot sources must yield
   every id they list, or cleanup deletes the missing ones.
5. **Never weaken the import safety nets** (no cleanup after `--limit` or errors, the 10%
   removal limit, `run_import` never raising) without being asked.
6. **Tests do not hit the network.** Mock HTTP with `httpx.MockTransport`; put real samples
   in `tests/fixtures/` with personal names removed.
7. **Keep the API backward compatible** for `/v1` (the iPhone app will depend on it): add
   fields, do not rename or remove them.
8. **Update the docs you invalidate.** API changes → `docs/api.md`; new source →
   `docs/data-sources.md` and the table in `backend/README.md`; new setting →
   `.env.example`, `compose.yaml`, `docs/operations.md`.
9. **Polish for labels shown on the phone, English for everything else.**
10. **Do not push, deploy or call external services with side effects** unless the user
    asked for that specific action.

## Facts that are easy to get wrong

- Numbers are stored as E.164 **integers without `+`** (`48717777777`), not strings.
- Timestamps are **naive UTC** (`models.utcnow()`), not timezone-aware.
- Listed (public) numbers are **never blocked by reports**; only a personal "block" blocks them.
- Prefix rules and unassigned UKE ranges apply **only at lookup** (`/v1/numbers`), never in
  the `/v1/directory` sync feed.
- `import all` runs `DEFAULT_SOURCES` (`uke bip nfz rpwdl apteki`), not every key of
  `SOURCES`; `ceidg` needs a token and runs in its own container.
- The pharmacy export is a legacy `.xls` read with `xlrd`; the register's CSV/XML URLs 404.
- CEIDG has never been run against the live API (no token yet); its paging assumptions are
  unverified.

## Where to look first

| Task | Start in |
|---|---|
| Wrong label or blocking decision | `directory.py` (`refresh_number`, `caller_id`), `tests/test_api.py` |
| Import problem | `importer.py`, `sources/<name>.py`, the run's error log in `import_runs` |
| API change | `api.py`, `tests/test_api.py`, `docs/api.md` |
| Admin page | `admin.py`, `templates/`, `tests/test_admin.py` |
| Alerts / health | `monitoring.py`, `tests/test_monitoring.py` |
| Deployment | `compose.yaml`, `Dockerfile`, `docs/operations.md` |
