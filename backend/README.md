# Phone Blocker backend

Stores two kinds of phone data and serves them to the iPhone app:

- **Public directory ("yellow pages")** – institutions and their published numbers,
  imported from the Polish BIP register (gov.pl/web/bip). These numbers get a caller-ID
  label and are never blocked.
- **Unwanted calls** – reports (telemarketing, scam, debt collection, …) in the style of
  sprawdzamnumer.pl. A number is blocked once its spam reports minus its "safe" reports reach
  `BLOCK_THRESHOLD`.

Python 3.11+, FastAPI, SQLAlchemy (SQLite by default, PostgreSQL via `DATABASE_URL`), and
`phonenumbers` (libphonenumber) for normalization.

## Run

```sh
uv sync
uv run phone-blocker crawl-bip                 # import all BIP institutions (resumable, skips cards newer than 7 days)
uv run phone-blocker crawl-bip --limit 20      # quick sample
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
