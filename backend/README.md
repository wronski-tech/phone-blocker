# Phone Blocker backend

The server side of Phone Blocker: a public phone directory imported from Polish registers,
spam reports, your personal block/allow lists and prefix rules, served to the iPhone app
through a JSON API, with a small admin page.

Python 3.11+, FastAPI, SQLAlchemy 2 with Alembic (SQLite for development, PostgreSQL in
production), libphonenumber.

| Guide | Contents |
|---|---|
| [Architecture](../docs/architecture.md) | Modules, data model, how caller ID is decided, sync versions, imports |
| [API reference](../docs/api.md) | Every endpoint with real examples, the iPhone sync contract |
| [Data sources](../docs/data-sources.md) | What each register provides and how it is imported; adding a source |
| [Operations](../docs/operations.md) | Deploying, configuration, updates, backups, monitoring, troubleshooting |
| [Development](../docs/development.md) | Setup, tests, conventions, schema changes |
| [AGENTS.md](AGENTS.md) | Rules for AI coding agents working here |

## Quick start

```sh
uv sync
uv run phone-blocker migrate                 # create ./phone_blocker.db
uv run phone-blocker import uke              # number ranges, seconds
uv run phone-blocker import apteki           # pharmacies, ~2 min
uv run uvicorn phone_blocker.api:create_app --factory --reload --port 8000
```

Open http://localhost:8000/docs for the API and http://localhost:8000/admin for the admin
page. Without `API_TOKEN` neither needs a password; set it for anything reachable from
outside.

## Commands

| Command | Does |
|---|---|
| `phone-blocker migrate` | Create or upgrade the schema in `DATABASE_URL` |
| `phone-blocker import <source>…` | Import sources: `uke bip nfz rpwdl apteki ceidg`, or `all` (= `uke bip nfz rpwdl apteki`) |
| `  --limit N` | Stop each source after N saved entries (a sample; removes nothing). Quick for `bip`; `nfz` still reads a whole voivodeship and `rpwdl`/`apteki` the whole file first |
| `  --delay S` | Seconds between requests (default per source) |
| `  --max-age-days D` | BIP: skip cards refreshed within D days (default 7) |
| `  --every-hours H` | Keep running and repeat H hours after each round (used by the importer container) |
| `phone-blocker import-bip-card <url>…` | Import specific BIP contact cards |
| `phone-blocker runs` | Show the 20 most recent import runs |
| `uv run pytest -q` | Run the tests (SQLite; set `TEST_DATABASE_URL` for PostgreSQL) |

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./phone_blocker.db` | Any SQLAlchemy URL; production uses `postgresql+psycopg://…` |
| `API_TOKEN` | unset (open) | Bearer token for `/v1` and the admin password |
| `BLOCK_THRESHOLD` | `1` | Net spam reports (spam − safe) needed to block a number |
| `NTFY_URL`, `NTFY_TOKEN` | unset | Push alerts for failed imports and backups |
| `BACKUP_DIR` | unset | Directory of `*.dump` files that `/status` checks |
| `CEIDG_TOKEN` | unset | Enables the `ceidg` source |

Production configuration goes in `.env` (copy `.env.example`); see
[Operations](../docs/operations.md#configuration-backendenv).

## Sources at a glance

| Source | What | Full run |
|---|---|---|
| `bip` | Public institutions (BIP contact cards) | hours; recent cards skipped |
| `nfz` | Clinics and hospital departments with an NFZ contract | about 2 h |
| `rpwdl` | Every healthcare provider with its facilities' and departments' numbers | about 5 min |
| `apteki` | Every active pharmacy | about 2 min |
| `uke` | Operator of every Polish number range; powers spoofing detection | seconds |
| `ceidg` | Sole traders (optional, needs a free token) | days at first, then minutes |

Details, limits and the rules for adding a source: [Data sources](../docs/data-sources.md).

## Deploy in short

```sh
git clone https://github.com/wronski-tech/phone-blocker.git && cd phone-blocker/backend
cp .env.example .env    # DOMAIN, POSTGRES_PASSWORD, API_TOKEN (openssl rand -hex 32)
docker compose up -d --build
```

Caddy gets the HTTPS certificate, the importer starts the first round of imports, and the
backup service dumps the database daily. Full guide: [Operations](../docs/operations.md).
