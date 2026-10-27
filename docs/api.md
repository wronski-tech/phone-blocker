# API reference

Base URL: `https://<DOMAIN>` in production, `http://localhost:8000` locally. The live,
always-current schema is at `/docs` (Swagger UI) and `/openapi.json`; this page explains the
behaviour behind it. The examples below are real responses.

## Conventions

- **Authentication.** Every `/v1` request needs `Authorization: Bearer <API_TOKEN>`. A missing
  or wrong token returns `401 {"detail": "Invalid or missing API token"}`. When the server has
  no `API_TOKEN` set (local development), no token is needed.
- **Phone numbers in requests** may be in any common format: `71 777 77 77`,
  `+48 71 777 77 77`, `0048717777777`. Numbers without a country code are read as Polish.
  An invalid number returns `422 {"detail": "Invalid phone number '123'"}`.
- **Phone numbers in responses** are E.164 digits without `+` as an integer
  (`48717777777`), the iOS `CXCallDirectoryPhoneNumber` format, plus `formatted`
  (`"+48 71 777 77 77"`) where useful.
- **Timestamps** are UTC without a timezone suffix (`2026-10-27T12:58:35.064875`).
- **Compression.** Responses over 1 kB are gzip-compressed when the client sends
  `Accept-Encoding: gzip` (URLSession does this automatically).

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /v1/numbers/{number}` | Everything about a number, including the effect of rules |
| `POST /v1/reports` | Report a call |
| `DELETE /v1/reports/{id}` | Undo a report |
| `PUT /v1/numbers/{number}/personal` | Set or clear your block/allow and label for a number |
| `GET /v1/personal` | Your block list, allow list and labels |
| `GET /v1/rules` | Prefix rules |
| `POST /v1/rules` | Add or replace a prefix rule |
| `DELETE /v1/rules/{id}` | Delete a rule |
| `GET /v1/organizations?q=` | Search the public directory |
| `GET /v1/directory?since=&limit=` | Sync feed for the Call Directory extension |
| `GET /health` | Liveness (public) |
| `GET /status` | Health checks for monitoring (public) |

### `GET /v1/numbers/{number}`

Who is calling. Works for any valid number, also ones the database has never seen (then
`label` is null and `listings`/`reports` are empty).

```json
{
  "number": 48717777777,
  "formatted": "+48 71 777 77 77",
  "label": "Urząd Miejski Wrocławia",
  "blocked": false,
  "rule": null,
  "personal": {"action": null, "label": null},
  "info": {"type": "fixed_line", "region": "Wrocław", "operator": "Netia S.A.", "service": null, "allocated": true},
  "listings": [
    {
      "kind": "phone",
      "department": null,
      "organization": {
        "id": 1, "name": "Urząd Miejski Wrocławia", "street": "Pl. Nowy Targ 1-8", "postal_code": "50-141",
        "city": "Wrocław", "commune": null, "county": null, "voivodeship": "Dolnośląskie",
        "website": "http://bip.um.wroc.pl", "email": "kum@um.wroc.pl", "nip": "8961003529", "regon": "001094670",
        "source": "bip", "source_id": "https://www.gov.pl/web/bip/urzad-miejski-wroclawia-dolnoslaskie-wroclaw-wroclaw",
        "phones": [
          {"number": 48717777777, "formatted": "+48 71 777 77 77", "kind": "phone", "department": null},
          {"number": 48717779061, "formatted": "+48 71 777 90 61", "kind": "phone", "department": "Redakcja BIP"}
        ]
      }
    }
  ],
  "reports": {"total": 0, "spam": 0, "safe": 0, "by_category": {}, "recent": []}
}
```

| Field | Meaning |
|---|---|
| `label`, `blocked` | What the phone should show and do, **including** prefix rules and the unassigned-range check (so they can differ from the `/v1/directory` entry). |
| `rule` | The rule with the longest prefix matching this number, or null. |
| `info.type` | `mobile`, `fixed_line`, `voip`, `toll_free`, `premium_rate`, `shared_cost`, `personal_number`, … or `unknown` (libphonenumber). |
| `info.region` | City for Polish landlines, otherwise the country (in Polish). |
| `info.operator` | Operator UKE assigned the range to (for mobiles the original one; numbers can be ported). Null when unknown or unassigned. |
| `info.service` | Service type of 70x/80x numbers. |
| `info.allocated` | `false`: UKE assigned the range to nobody, so the caller ID is probably spoofed. `null`: unknown (foreign numbers, ranges missing from the UKE tables, or the `uke` import has not run). |
| `reports.recent` | The newest 20 reports, newest first. |

### `POST /v1/reports`

```json
{"number": "+48 500 100 200", "category": "telemarketing", "comment": "Fotowoltaika"}
```

Returns `201` with the number in the same shape as the lookup, now reflecting the report
(`"label": "Spam: Telemarketing (1)", "blocked": true` with the default threshold of 1).

Categories (the Polish label shown on the phone in brackets): `telemarketing`
(Telemarketing), `scam` (Oszustwo), `debt_collection` (Windykacja), `survey` (Ankieta),
`robocall` (Automat), `silent` (Głuchy telefon), `other` (Niechciany), and `safe`, which
vouches for a number and cancels one spam report. `comment` is optional, up to 1000
characters.

A number is labelled when it has more spam reports than safe ones, and blocked when
`spam − safe ≥ BLOCK_THRESHOLD`. Reports never block a number listed in the public
directory.

### `DELETE /v1/reports/{id}`

Undo a report (ids are in `reports.recent`). `204`, or `404` if it does not exist.

### `PUT /v1/numbers/{number}/personal`

```json
{"action": "allow", "label": "Dr Nowak"}
```

- `action`: `"block"` (always block, even listed numbers), `"allow"` (never block, hide
  spam labels), or `null`.
- `label`: your own caller-ID label (up to 200 characters), or `null`.

Both fields are replaced on every call, so send nulls to clear. Returns the number like the
lookup.

### `GET /v1/personal`

```json
[{"action": "allow", "label": "Dr Nowak", "number": 48600700800, "formatted": "+48 600 700 800"}]
```

### Rules: `GET /v1/rules`, `POST /v1/rules`, `DELETE /v1/rules/{id}`

```json
{"prefix": "+44 70", "action": "block", "note": "UK personal numbers"}
```

returns `201`:

```json
{"id": 1, "prefix": "4470", "formatted": "+44 70", "action": "block", "note": "UK personal numbers", "created_at": "2026-10-27T12:58:35.100452"}
```

- `prefix` must start with `+` or `00` and a valid country code (`422` otherwise). Posting a
  prefix that already has a rule replaces it.
- `block` blocks every number starting with the prefix; numbers it blocks are labelled with
  the note (or "Reguła +44 70").
- `allow` exempts the prefix from block rules and from blocking unassigned numbers. An allow
  rule for `+48` turns the spoofing check off entirely.
- The longest matching prefix wins. Personal settings, public listings and blocks from
  reports beat rules.
- Rules are **not** included in `/v1/directory` (see [architecture](architecture.md#rules-and-spoofing)).

### `GET /v1/organizations?q=…&limit=50`

Organizations whose name, city, commune or department names contain every word of `q`
(at least 2 characters), ignoring case and Polish diacritics: `q=urzad wroclaw` finds
"Urząd Miejski Wrocławia". `limit` is 1–200. Returns a list of organizations in the shape
shown under `listings[].organization` above.

### `GET /v1/directory?since=0&limit=10000`

The feed the iPhone Call Directory extension syncs from. `limit` is 1–50,000.

```json
{
  "entries": [
    {"number": 48717777777, "label": "Urząd Miejski Wrocławia", "blocked": false},
    {"number": 48717779061, "label": "Urząd Miejski Wrocławia – Redakcja BIP", "blocked": false}
  ],
  "next_since": 2,
  "has_more": true
}
```

## Syncing the iPhone

Every change to a number's `label` or `blocked` takes a new, increasing `version`; the feed
is ordered by it.

1. **First install:** call `?since=0` and follow `next_since` while `has_more` is true.
   With `since=0` only active entries (a label or blocked) are returned.
2. **Later:** call with `since=<the last next_since>`. Each entry replaces whatever the
   phone had for that number; `"label": null, "blocked": false` means remove it.
3. **CallKit** requires numbers added in ascending order, so sort each batch by `number`
   before adding blocking and identification entries.
4. Store `next_since` only after the batch was applied, so an interrupted sync repeats
   rather than skips.

## `GET /health` and `GET /status`

- `/health` → `200 {"status": "ok"}` when the API runs and reaches its database, `503`
  otherwise. The Docker health check uses it.
- `/status` → `200` when every check passes, `503` otherwise:

```json
{
  "ok": false,
  "checks": {
    "database": {"ok": true},
    "import:uke": {"ok": true, "last_success": "2026-10-27T11:38:00.708884"},
    "import:bip": {"ok": false, "last_success": null},
    "backup": {"ok": true, "newest": "2026-10-27T11:38:50.317975", "file": "phone_blocker-20261027-1138.dump"}
  }
}
```

There is one `import:<source>` check per source in `import all` (ok when its last successful
run finished less than 3 days ago), and a `backup` check (newest dump under 2 days old) when
`BACKUP_DIR` is set. Point an external uptime monitor at it; see
[operations.md](operations.md#monitoring).

## Errors

| Status | When |
|---|---|
| `401` | Missing or wrong bearer token |
| `404` | Report or rule id does not exist |
| `422` | Invalid phone number, prefix, category, or a field over its length limit (FastAPI validation errors have `detail` as a list) |
| `503` | `/health` or `/status` checks fail |
