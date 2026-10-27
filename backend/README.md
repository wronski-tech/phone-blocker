# Phone Blocker backend

Stores two kinds of phone data and serves them to the iPhone app:

- **Public directory ("yellow pages")** – organizations and their published numbers,
  imported from public registers (see [Directory sources](#directory-sources)). These numbers
  get a caller-ID label and are never blocked.
- **Unwanted calls** – reports (telemarketing, scam, debt collection, …) in the style of
  sprawdzamnumer.pl. A number is blocked once its spam reports minus its "safe" reports reach
  `BLOCK_THRESHOLD`.

Python 3.11+, FastAPI, SQLAlchemy (SQLite by default, PostgreSQL via `DATABASE_URL`), and
`phonenumbers` (libphonenumber) for normalization.

## Run

```sh
uv sync
uv run phone-blocker migrate                   # create or upgrade the schema
uv run phone-blocker import all                # import every directory source (hours)
uv run phone-blocker import nfz --limit 20     # quick sample of one source
uv run phone-blocker runs                      # recent import runs
uv run phone-blocker import-bip-card https://www.gov.pl/web/bip/urzad-miejski-wroclawia-dolnoslaskie-wroclaw-wroclaw
API_TOKEN=change-me uv run uvicorn phone_blocker.api:create_app --factory --port 8000
uv run pytest
```

| Variable          | Default                         | Meaning                                         |
|-------------------|---------------------------------|-------------------------------------------------|
| `DATABASE_URL`    | `sqlite:///./phone_blocker.db`  | Any SQLAlchemy URL                              |
| `API_TOKEN`       | unset (no auth)                 | Required as `Authorization: Bearer <token>` on `/v1` |
| `BLOCK_THRESHOLD` | `1`                             | Net spam reports needed to block a number       |

Interactive API docs: `/docs`.

## Directory sources

| Source | What | How | Full run |
|--------|------|-----|----------|
| `bip`  | Public institutions from the BIP register | JSON tree behind gov.pl/web/bip/spis-podmiotow, then each HTML contact card | hours; cards refreshed within `--max-age-days` (7) are skipped |
| `nfz`  | Clinics and hospital departments with an NFZ contract | Public NFZ "Terminy leczenia" API, grouped per department | about 2 h |

Each run is recorded in `import_runs` (`phone-blocker runs`). After a **complete** run, entries
the source no longer lists are removed and their numbers lose their label in the next sync.
Runs stopped by `--limit` or by an error remove nothing, and a run that would remove more
than 10% of a source's entries removes nothing and says so in the run message.

To add a source, write a module in `src/phone_blocker/sources/` with `DEFAULT_DELAY` and
`iter_records(ctx, client)` (contract in `sources/__init__.py`), and register it in
`importer.SOURCES`.

## Schema changes

The schema is managed by Alembic; migrations live in
`src/phone_blocker/migrations/versions/` and ship inside the package.

1. Change `models.py`.
2. `uv run phone-blocker migrate` (bring your dev database to the latest revision), then
   `uv run alembic revision --autogenerate -m "describe the change"`.
3. Review the generated file, then run `uv run phone-blocker migrate` again.

`test_migrations_match_models` fails if a model changes without a migration. The Docker
container runs `phone-blocker migrate` before starting the API, so deploying applies new
migrations automatically.

## Deploy

`compose.yaml` runs PostgreSQL, the API, the importer (all directory sources on start, then
24 h after each round ends), and Caddy, which gets a Let's Encrypt certificate and redirects
HTTP to HTTPS. Any Linux VPS with Docker works (Hetzner, OVH, DigitalOcean…).

1. Point a domain's DNS A/AAAA record at the server and open ports 80 and 443.
2. On the server:

   ```sh
   git clone https://github.com/wronski-tech/phone-blocker.git && cd phone-blocker/backend
   cp .env.example .env    # set DOMAIN, POSTGRES_PASSWORD, API_TOKEN (openssl rand -hex 32)
   docker compose up -d --build   # the importer starts the first import right away
   ```

3. Check: `curl https://<DOMAIN>/health` returns `{"status":"ok"}`. Follow the import with
   `docker compose logs -f importer` and `docker compose exec api phone-blocker runs`.

Update with `git pull && docker compose up -d --build`. The database lives in the `db-data`
volume and survives rebuilds; back it up with
`docker compose exec db pg_dump -U phone_blocker phone_blocker > backup.sql`.

Run the tests against PostgreSQL with
`TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db uv run pytest` (wipes that database).

## API

| Endpoint                         | Purpose                                           |
|----------------------------------|---------------------------------------------------|
| `GET /v1/numbers/{number}`       | Who is calling: label, blocked, listings, reports |
| `POST /v1/reports`               | Report a call: `{number, category, comment?}`     |
| `GET /v1/organizations?q=…`      | Search the directory (case and diacritics insensitive) |
| `GET /v1/directory?since=&limit=`| Sync feed for the Call Directory extension        |

Numbers are accepted in any common format (`71 777 77 77`, `+48717777777`, …) and returned
as E.164 digits without `+` (`48717777777`), which is the `CXCallDirectoryPhoneNumber` format.

Report categories: `telemarketing`, `scam`, `debt_collection`, `survey`, `robocall`,
`silent`, `other`, and `safe` (vouches for a number).

### Syncing the iPhone

Every change to a number's `label` or `blocked` flag takes a new, increasing `version`.

1. First install: call `/v1/directory?since=0` and follow `next_since` while `has_more`.
   This returns only active entries.
2. Later: call with `since=<last next_since>`. Each entry replaces the previous state of that
   number; `label: null, blocked: false` means remove it.
3. CallKit requires numbers added in ascending order, so sort each batch by `number` before
   adding blocking and identification entries.
