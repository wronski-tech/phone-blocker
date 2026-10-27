# backend/AGENTS.md

Applies to everything under `backend/`. The repository-wide rules are in `../AGENTS.md`;
design background is in `../docs/architecture.md`.

## Module ownership (`src/phone_blocker/`)

| Module | Owns | Do not |
|---|---|---|
| `models.py` | Tables and columns | Change without an Alembic migration |
| `directory.py` | Saving organizations, deriving label/blocked, sync versions, rules, search | Duplicate its logic elsewhere |
| `phone.py` | Parsing and formatting numbers and prefixes | Write new number parsing elsewhere; new sources use `find_numbers` (`bip`, `nfz` and `ceidg` predate it and call libphonenumber directly) |
| `importer.py` | Running sources, `import_runs`, cleanup, safety limits, alerts | Put source-specific code here |
| `sources/*.py` | Fetching and parsing one register each | Access the database |
| `api.py` | `/v1`, `/health`, `/status`, response models | Put business rules here; call `directory.py` |
| `admin.py`, `templates/` | `/admin` HTML pages | Skip `require_admin` or the same-origin POST check |
| `monitoring.py` | ntfy alerts, `/status` checks | Let `send_alert` raise |
| `cli.py` | The `phone-blocker` command | |
| `config.py` | `Settings.from_env()` | Read `os.environ` elsewhere (exception: `CEIDG_TOKEN` in `sources/ceidg.py`) |
| `migrations/` | Alembic environment and versions | Edit pushed versions |

## Patterns to copy

- **New endpoint:** add it inside `create_app` on the `v1` router (token required), with a
  Pydantic response model, then a test in `tests/test_api.py` that goes through
  `TestClient`. Use `parse_number()` for path or body numbers so invalid input returns 422.
- **Mutation:** load or create with `get_or_create_phone`, change through a `directory.py`
  function, `session.commit()`, return `number_out(session, phone)`.
- **Test database:** use the `db_url` fixture (fresh migrated SQLite, or PostgreSQL when
  `TEST_DATABASE_URL` is set).
- **Source test:** feed real sample data through `httpx.MockTransport` and assert the
  parsed `OrganizationRecord`s, including entries that must be skipped
  (`tests/test_registers.py` is the reference).

## Verification before you finish

1. `uv run pytest -q` passes.
2. `uvx pyflakes src tests` prints nothing.
3. Model, migration or query changes: also run the suite on PostgreSQL (see `../AGENTS.md`).
4. Source changes: a real import into a scratch database
   (`DATABASE_URL=sqlite:////tmp/try.db`) gives sensible counts and labels; delete the file after.
5. Template changes: look at the rendered pages, including empty and error states.
6. `docker compose config -q` (with `DOMAIN`, `POSTGRES_PASSWORD`, `API_TOKEN` set to dummy
   values in the environment) after editing `compose.yaml`.
