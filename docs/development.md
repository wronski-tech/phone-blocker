# Development

How to work on the backend: setup, tests, conventions and common changes. AI agents should
also read [AGENTS.md](../AGENTS.md), which summarises the rules.

## Setup

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/). Docker only for the
production stack.

```sh
cd backend
uv sync                                   # creates .venv with dev dependencies (pytest)
uv run phone-blocker migrate              # creates ./phone_blocker.db (SQLite)
uv run phone-blocker import uke           # seconds; enables operator info and spoofing checks
uv run phone-blocker import apteki        # ~2 min; real directory data to play with
uv run uvicorn phone_blocker.api:create_app --factory --reload --port 8000
```

Then open http://localhost:8000/docs (API) and http://localhost:8000/admin (no password
while `API_TOKEN` is unset). Use `DATABASE_URL=sqlite:////tmp/scratch.db` to keep
experiments out of your main dev database.

## Tests

```sh
uv run pytest -q                          # SQLite, ~6 s
TEST_DATABASE_URL=postgresql+psycopg://postgres:pw@127.0.0.1:55432/postgres uv run pytest -q
```

For PostgreSQL, start a throwaway server first:
`docker run -d --rm --name pgtest -e POSTGRES_PASSWORD=pw -p 55432:5432 postgres:17-alpine`.
The suite **wipes** the database in `TEST_DATABASE_URL`.

CI ([`.github/workflows/backend.yml`](../.github/workflows/backend.yml)) runs both variants
and builds the Docker image, starts it on an empty database and waits for `/health`, on
every push to `main` and every pull request touching `backend/`.

| Test file | Covers |
|---|---|
| `test_api.py` | Reports, blocking, sync feed, personal settings, rules, search, validation |
| `test_admin.py` | Admin auth, cross-site form protection, editing numbers and rules |
| `test_importer.py` | Cleanup after complete runs, nothing removed on partial or failed runs, the 10% safety limit, alerts |
| `test_monitoring.py` | `/health`, `/status` and their staleness limits |
| `test_migrations.py` | Models and migrations match (fails if you forget a migration) |
| `test_bip.py`, `test_nfz.py`, `test_uke.py`, `test_ceidg.py`, `test_registers.py` | Each source's parsing against real sample data, mocked HTTP |

Tests never call the real registers: HTTP goes through `httpx.MockTransport`, and fixtures
in `tests/fixtures/` hold real samples (personal names removed).

## Conventions

- **Caller-ID logic lives in `directory.py` only.** Anything that changes listings, reports
  or personal settings must end in `refresh_number(session, phone, block_threshold)` so the
  label, block flag and sync version stay right. Never set `PhoneNumber.label`, `.blocked`
  or `.version` anywhere else.
- **Sources only fetch and parse.** No database access in `sources/`; they yield
  `OrganizationRecord`s and the importer saves them.
- **Phone numbers** are parsed with `phone.normalize` (one user-typed number) or
  `phone.find_numbers` (free text from registers), and stored as E.164 integers.
- **Timestamps** are naive UTC from `models.utcnow()`.
- **Schema changes** always come with an Alembic migration (below).
- **Small and plain:** standard library and existing dependencies first, no new layers or
  abstractions for one use, comments only where the reason is not obvious.
- **Tests** check behaviour through public interfaces (API responses, parsed records,
  database state) with inputs where a wrong implementation would fail, not call order or
  private helpers.
- **Labels are Polish** (they are shown on a Polish phone); code, comments and docs are English.

## Schema changes

1. Edit `models.py`.
2. Generate a migration against an up-to-date scratch database:

   ```sh
   export DATABASE_URL=sqlite:////tmp/gen.db
   uv run phone-blocker migrate
   uv run alembic revision --autogenerate -m "short description"
   ```

3. Review the file in `src/phone_blocker/migrations/versions/` (remove the
   `### commands auto generated` comments, check renames were not turned into drop + add),
   then run `uv run pytest -q`.

SQLite cannot `ALTER` most things, so `env.py` turns on Alembic batch mode for SQLite.
Production applies migrations on container start.

## Common changes

| Change | Where |
|---|---|
| New directory source | [data-sources.md → Adding a source](data-sources.md#adding-a-source) |
| New report category | `SPAM_CATEGORIES` in `directory.py` (key and Polish label) |
| Different label or blocking rules | `refresh_number` and `caller_id` in `directory.py`, plus tests in `test_api.py` |
| New API endpoint | `api.py` (inside `create_app`, on the `v1` router so it requires the token) and a test in `test_api.py`; document it in [api.md](api.md) |
| New admin page | `admin.py` route + template in `templates/` extending `base.html` |
| New setting | `Settings` in `config.py`, `compose.yaml` environment, `.env.example`, [operations.md](operations.md#configuration-backendenv) |
| New `/status` check | `monitoring.status` and `test_monitoring.py` |

## Checking UI changes

The admin page has no frontend build; templates render on the server. After changing a
template, run the server and look at the affected pages (and their non-default states:
empty tables, failed runs, validation errors) in a browser before committing.

## Commits

- One logical change per commit, with a message that says what changed and why.
- CI must pass on `main`.
