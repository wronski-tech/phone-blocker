# Architecture

How the backend is built and why. For the HTTP contract see [api.md](api.md); for each
importer see [data-sources.md](data-sources.md).

## Components

```diagram
                 ┌──────────────────────────── backend/src/phone_blocker ───────────────────────────┐
                 │                                                                                  │
 public          │  sources/*.py ──▶ importer.py ──▶ directory.py ◀── api.py ◀── HTTP /v1, /status   │
 registers ─────▶│  (fetch+parse)    (runs, cleanup)  (rules of      admin.py ◀── HTTP /admin        │
                 │                                    caller ID)                                    │
                 │                        │                │                                         │
                 │                        ▼                ▼                                         │
                 │                   models.py (SQLAlchemy) ──▶ PostgreSQL / SQLite                  │
                 │                   migrations/ (Alembic)                                          │
                 │                                                                                  │
                 │  cli.py: migrate, import, runs        monitoring.py: ntfy alerts, /status checks  │
                 └──────────────────────────────────────────────────────────────────────────────────┘
```

| Module | Owns |
|--------|------|
| `models.py` | The schema (tables below). Every change needs an Alembic migration. |
| `directory.py` | All caller-ID logic: saving organizations, deriving each number's `label`/`blocked`, sync versions, rules, search. The single source of truth for "what should the phone show". |
| `phone.py` | Number parsing and formatting (libphonenumber): `normalize`, `find_numbers` (free text from registers), prefixes. |
| `importer.py` | Running a source: the `import_runs` record, cleanup of entries a source dropped, safety limits, alerts. |
| `sources/` | One module per register; only fetching and parsing, no database code. |
| `api.py` | The JSON API (`/v1`, `/health`, `/status`) and response models. |
| `admin.py` + `templates/` | The server-rendered admin page at `/admin`. |
| `monitoring.py` | ntfy push alerts and the health checks behind `/status`. |
| `cli.py` | The `phone-blocker` command (`migrate`, `import`, `runs`, `import-bip-card`). |
| `config.py` | `Settings` read from environment variables. |
| `db.py` | Engine/session factory and `migrate()`. |

## Data model

```diagram
┌──────────────────┐ 1   * ┌──────────┐ *   1 ┌───────────────────┐
│ organizations    │──────▶│ listings │──────▶│ phone_numbers     │
│ source+source_id │       │ kind     │       │ number (E.164 int)│
│ name, address,   │       │ depart-  │       │ label, blocked    │◀── derived
│ search_text      │       │ ment     │       │ version           │◀── sync cursor
└──────────────────┘       └──────────┘       │ personal_action   │◀── your settings
                                              │ personal_label    │
                                              └─────────┬─────────┘
                                                        │ 1
                                                        │ *
                                              ┌─────────┴─────────┐
                                              │ reports           │
                                              │ category, comment │
                                              └───────────────────┘

 rules (prefix, action, note)      number_ranges (UKE prefix → operator)
 import_runs (one row per run)     source_states (progress of incremental sources)
 sync_state (single row: last issued version)
```

- **`phone_numbers.number`** is E.164 without `+` as an integer (`48717777777`), the format
  iOS `CXCallDirectoryPhoneNumber` uses.
- **`label` and `blocked` are derived**, never edited directly. `directory.refresh_number`
  recomputes them from listings, reports and personal settings whenever any of those change.
- **`organizations`** are identified by `(source, source_id)`, so each importer owns its rows
  and can update or remove them without touching other sources.
- **`rules` and `number_ranges`** cover whole ranges, so they are applied at lookup time
  (see [Rules and spoofing](#rules-and-spoofing)) rather than stored per number.

## How a number's caller ID is decided

`directory.refresh_number` stores the result in `phone_numbers`; `directory.caller_id` adds
rules and unassigned ranges on top when a number is looked up.

```diagram
 personal_action = block ──────────────────────────────────▶ blocked (label kept)
 personal_label set ───────────────────────────────────────▶ that label
 listed by an organization ────────────────────────────────▶ organization label, never blocked
 personal_action = allow ──────────────────────────────────▶ not blocked, no spam label
 spam reports > safe reports ──────────────────────────────▶ "Spam: <top category> (n)"
 spam − safe ≥ BLOCK_THRESHOLD ────────────────────────────▶ blocked
 ─ at lookup only: numbers with no listing, no personal action, not already blocked ─
 longest matching rule = block ────────────────────────────▶ blocked, labelled with the note
 Polish number in an unassigned UKE range, no rule ────────▶ blocked as spoofed
```

When a number has several listings, the label comes from the best one: phones before
faxes, then listings without a department, then the oldest. A department is appended as
"Name – Department", a fax gets "(faks)", and labels are cut to 200 characters.

## Sync versions

Every time a number's `label` or `blocked` changes, it gets the next value of the single
`sync_state.version` counter. Incrementing it with `UPDATE … RETURNING` locks that row until
the transaction commits, so versions become visible in increasing order and a client that
asks for "everything after version N" never skips a change. A number whose label and block
both become empty stays in the table with a new version, which the phone reads as "remove
this number". See [api.md](api.md#syncing-the-iphone).

## Imports

```diagram
 importer.run_import(source)
   │ 1. insert import_runs row (status running)
   │ 2. source.iter_records(ctx, client) yields (source_id, record | None)
   │      record     → directory.save_record: upsert organization + listings,
   │                   refresh every affected number
   │      None       → keep the existing entry (fresh, or fetching it failed)
   │ 3. complete run → remove organizations whose source_id was not yielded,
   │                   unless that is more than 10% of the source (then refuse and alert)
   │ 4. finish the run row (success / failed, counts, error log), alert on failure
```

Three kinds of source share this flow:

| Kind | Example | Contract |
|------|---------|----------|
| Snapshot | `bip`, `nfz`, `rpwdl`, `apteki` | `iter_records` yields every entry the source lists; cleanup removes the rest. |
| Incremental | `ceidg` | `INCREMENTAL = True`; yields only changes, `None` means delete; progress kept in `source_states` via `ctx.state` and `ctx.checkpoint()`. |
| Reference table | `uke` | `replace_all(session, client, ctx)` replaces `number_ranges` wholesale. |

Safety properties that tests guard:

- A run stopped by `--limit` or an exception removes nothing.
- A run that would remove more than 10% of a source's entries (and more than 10) removes
  nothing and records "Refused to remove …".
- `run_import` never raises, so the scheduler loop keeps going after a failed source.
- Progress is saved every 100 entries, so the admin page shows long runs advancing.

## Rules and spoofing

Rules (`+44 70` → block) and UKE's unassigned ranges (about 400 million Polish numbers)
cover far more numbers than the iPhone Call Directory extension can hold, which only takes
individual numbers. They are therefore **not** in `/v1/directory`; they apply in
`/v1/numbers` lookups (the basis for a future Live Caller ID Lookup server) and the app can
fetch `/v1/rules` to add small prefixes itself.

## Authentication

- `/v1/*`: `Authorization: Bearer <API_TOKEN>` (compared in constant time). With no
  `API_TOKEN` set, the API is open; that is meant for local development only.
- `/admin`: HTTP Basic, any user name, `API_TOKEN` as the password. Because browsers resend
  Basic credentials automatically, POST forms must come from the same origin (checked via
  `Origin`/`Referer`).
- `/health`, `/status`, `/docs`: public.

## Design decisions

| Decision | Why |
|----------|-----|
| Derived `label`/`blocked` columns plus a version counter | The phone syncs a flat list of numbers incrementally; computing it per request would not scale to the full directory. |
| Listed numbers are never blocked by reports | A public institution's number can be reported by mistake or maliciously; the directory is the stronger signal. Personal "always block" still wins. |
| Each source owns `(source, source_id)` rows | Re-imports update in place and cleanup cannot delete another source's data. |
| Refuse large removals | A register outage or format change looks like "everything disappeared"; wiping the directory would be worse than keeping stale entries. |
| Rules applied at lookup, not stored | A prefix can match millions of numbers. |
| Naive UTC timestamps | SQLite and PostgreSQL behave the same. |
| SQLite for development, PostgreSQL in production | Zero-setup local runs; CI runs the suite on both. |
| Server-rendered admin page | No frontend build; it only needs to work for one person. |
