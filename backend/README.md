# Phone Blocker backend

Stores two kinds of phone data and serves them to the iPhone app:

- **Public directory ("yellow pages")** – organizations and their published numbers,
  imported from public registers (see [Directory sources](#directory-sources)). These numbers
  get a caller-ID label and are never blocked.
- **Unwanted calls** – reports (telemarketing, scam, debt collection, …) in the style of
  sprawdzamnumer.pl. A number is blocked once its spam reports minus its "safe" reports reach
  `BLOCK_THRESHOLD`.
- **Personal settings** – your own block list, allow list and labels, which beat everything
  else. An allowed number is never blocked and shows no spam label.

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

GitHub Actions ([`.github/workflows/backend.yml`](../.github/workflows/backend.yml)) runs the
tests on SQLite and PostgreSQL and builds and starts the Docker image on every push to `main`
and every pull request that touches `backend/`.

| Variable          | Default                         | Meaning                                         |
|-------------------|---------------------------------|-------------------------------------------------|
| `DATABASE_URL`    | `sqlite:///./phone_blocker.db`  | Any SQLAlchemy URL                              |
| `API_TOKEN`       | unset (no auth)                 | Required as `Authorization: Bearer <token>` on `/v1` |
| `BLOCK_THRESHOLD` | `1`                             | Net spam reports needed to block a number       |

Interactive API docs: `/docs`. Responses over 1 kB are gzip-compressed when the client
accepts it (the iOS URL session does), which shrinks the full directory download several times.

## Directory sources

| Source | What | How | Full run |
|--------|------|-----|----------|
| `bip`  | Public institutions from the BIP register | JSON tree behind gov.pl/web/bip/spis-podmiotow, then each HTML contact card | hours; cards refreshed within `--max-age-days` (7) are skipped |
| `nfz`  | Clinics and hospital departments with an NFZ contract | Public NFZ "Terminy leczenia" API, grouped per department | about 2 h |
| `uke`  | Operator of every Polish number range (landline, mobile, VoIP, 70x/80x) | UKE numbering tables, CSV export from numeracja.uke.gov.pl | seconds; replaces the table each run |
| `ceidg` | Sole traders that published a phone number in CEIDG (optional) | CEIDG API v3 with a free token in `CEIDG_TOKEN`; first import month by month, then the daily change feed | first import: days (1000 requests/h); then minutes |

`import all` runs `uke`, `bip` and `nfz`. CEIDG runs in its own `ceidg` container: get a
token at [dane.biznes.gov.pl](https://dane.biznes.gov.pl) ("Dane po API") and set
`CEIDG_TOKEN` and `COMPOSE_PROFILES=ceidg` in `.env`. Its first import covers about
2.6 million active businesses at the API's limit of 1000 requests per hour, so it takes
several days; it saves its progress after every month of start dates and continues after
restarts. After that, each daily run only fetches businesses that changed.

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
24 h after each round ends), daily backups, and Caddy, which gets a Let's Encrypt certificate
and redirects HTTP to HTTPS. Any Linux VPS with Docker works (Hetzner, OVH, DigitalOcean…).

1. Point a domain's DNS A/AAAA record at the server and open ports 80 and 443.
2. On the server:

   ```sh
   git clone https://github.com/wronski-tech/phone-blocker.git && cd phone-blocker/backend
   cp .env.example .env    # set DOMAIN, POSTGRES_PASSWORD, API_TOKEN (openssl rand -hex 32)
   docker compose up -d --build   # the importer starts the first import right away
   ```

3. Check: `curl https://<DOMAIN>/health` returns `{"status":"ok"}`, then open
   `https://<DOMAIN>/admin` and log in with any user name and `API_TOKEN` as the password.

Update with `git pull && docker compose up -d --build`. The database lives in the `db-data`
volume and survives rebuilds.

### Admin page

`/admin` shows counts, every import run with its error log, and the latest reports. Search
for a number to see everything about it, undo reports, or set your own label and
always/never block. Imported organizations are not edited there, because the next import
would overwrite the edit; fix a wrong label per number instead.

### Backups

The `backup` service writes a compressed `pg_dump` to `backend/backups/` right after start
and then daily, keeping the newest 14. Copy that folder off the server too (e.g. with
`rsync` to another machine); a backup on the same disk doesn't survive losing the server.
To restore one:

```sh
docker compose stop api importer
docker compose exec -T db pg_restore -U phone_blocker -d phone_blocker --clean --if-exists < backups/phone_blocker-YYYYMMDD-HHMM.dump
docker compose start api importer
```

Run the tests against PostgreSQL with
`TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db uv run pytest` (wipes that database).

## API

| Endpoint                         | Purpose                                           |
|----------------------------------|---------------------------------------------------|
| `GET /v1/numbers/{number}`       | Who is calling: label, blocked, listings, reports, and `info` (type, city, assigned operator, unallocated range) for any number |
| `POST /v1/reports`               | Report a call: `{number, category, comment?}`     |
| `DELETE /v1/reports/{id}`        | Undo a report                                     |
| `PUT /v1/numbers/{number}/personal` | Your settings: `{action: "block" \| "allow" \| null, label}`; nulls clear them |
| `GET /v1/personal`               | Your block list, allow list and personal labels   |
| `GET /v1/organizations?q=…`      | Search the directory (case and diacritics insensitive) |
| `GET /v1/directory?since=&limit=`| Sync feed for the Call Directory extension        |

`info` comes from libphonenumber and the UKE tables and is available for every number, but
only through lookup: the Call Directory extension can only label numbers listed one by one.

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
