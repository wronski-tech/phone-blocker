# Data sources

Every source is a module in `backend/src/phone_blocker/sources/`. Run one with
`phone-blocker import <name>`; `phone-blocker import all` runs `uke bip nfz rpwdl apteki`.
Figures below are from real runs in October 2026.

| Source | Register | Publisher | Access | Entries | Full run |
|---|---|---|---|---|---|
| `bip` | Biuletyn Informacji Publicznej (public institutions) | gov.pl | open | thousands of institutions | hours |
| `nfz` | NFZ "Terminy leczenia" (clinics with an NFZ contract) | Narodowy Fundusz Zdrowia | open API | departments of contracted providers | about 2 h |
| `rpwdl` | Rejestr Podmiotów Wykonujących Działalność Leczniczą | Centrum e-Zdrowia | open daily ZIP | 29,746 providers, 63,160 numbers | about 5 min |
| `apteki` | Rejestr Aptek | Centrum e-Zdrowia | open daily spreadsheet | 13,357 pharmacies | about 2 min |
| `uke` | Polish numbering plan allocations | UKE | open CSV | 48,428 prefixes | seconds |
| `ceidg` | CEIDG (sole traders), optional | Ministry of Development | free token | up to ~2.6 M businesses | first import days |

## `bip` – public institutions

- **Discovery:** the JSON tree behind https://www.gov.pl/web/bip/spis-podmiotow
  (`aplikacje.gov.pl/app/bip-back/api/subjects`), walked breadth-first.
- **Numbers:** each institution's HTML contact card, e.g.
  https://www.gov.pl/web/bip/urzad-miejski-wroclawia-dolnoslaskie-wroclaw-wroclaw. Phones and
  faxes from the "Dane podmiotu" section have no department; those from other sections (for
  example "Redakcja BIP") get the section name as department.
- **`source_id`:** the card URL.
- **Freshness:** cards refreshed within `--max-age-days` (default 7) are skipped and kept, so
  daily runs only re-fetch about a seventh of the cards. Cards that fail to load are kept too.
- **One card by hand:** `phone-blocker import-bip-card <url>`.

## `nfz` – clinics with an NFZ contract

- **API:** https://api.nfz.gov.pl/app-itl-api/queues, per voivodeship, 25 rows per page.
- Rows repeat per medical service, so they are grouped into one organization per place
  (provider code + place + address). The place name becomes the department unless it equals
  the provider name. Long legal forms are abbreviated ("NZOZ", "SP ZOZ", "SP. Z O.O.", "S.A.").
- **`source_id`:** `<voivodeship>/<provider code>/<place>/<address>/<city>`.

## `rpwdl` – healthcare providers

- **File:** `https://rpwdl2.ezdrowie.gov.pl/api/rpwdl-public-resource/ledgers-zip/initial?fileTypeInsideZip=CSV&activityType=HEALTHCARE_PROVIDER&activeLedgers=true`,
  a ~35 MB ZIP regenerated daily with `podmioty.csv` (providers), `zaklady.csv` (facilities),
  `jednostki.csv` (units) and `komorki.csv` (departments), each with a `Telefon` column.
- **One organization per provider** (`ID Księgi` is the `source_id`). Removed providers
  (`Data wykreślenia z rejestru`) and closed units (`Data zakończenia działalności…`) are
  skipped.
- **Departments:** a number the provider lists itself has no department. A number listed
  only further down gets the name of the unit at the highest level that lists it; if several
  units at that level share it, it gets no department. Names over 200 characters are cut.
- **Left out:** individual practices of doctors, nurses, physiotherapists and lab
  diagnosticians (other `activityType` files), because they are mostly private mobiles.

## `apteki` – pharmacies

- **File:** https://rejestry.ezdrowie.gov.pl/api/ra/filegenerator/getxls, a ~32 MB legacy
  `.xls` (read with `xlrd`) with one row per pharmacy ever registered.
- Only `stan_apteki = AKTYWNA` rows with a valid number are kept. `telefon` numbers are
  phones, `fax` numbers faxes. **`source_id`:** `identyfikator_apteki`.
- **Name:** `nazwa_apteki`, or the owner's name when empty, prefixed with "Apteka" (or
  "Punkt apteczny" for outlets) unless it already says so.
- The CSV and XML links listed on dane.gov.pl returned 404 when this was built; only the
  spreadsheet works.

## `uke` – number range allocations

- **Files:** `https://numeracja.uke.gov.pl/pl/{pstn,plmn,voip,ndin}_tables/export.csv`
  (landline, mobile, VoIP, 70x/80x services), cp1250-encoded.
- Range notation like `121(0,3-5)` expands to `1210, 1213, 1214, 1215`.
- Replaces the whole `number_ranges` table each run; feeds `info` in lookups and the
  spoofing check. Operator ids from 99990 up are UKE reserves ("Rezerwa Prezesa UKE",
  "Rezerwa techniczna", "Rezerwa regulacyjna"): numbers there are unassigned.

## `ceidg` – sole traders (optional)

- **API:** CEIDG data warehouse API v3, https://dane.biznes.gov.pl/api/ceidg/v3, with a free
  JWT token from https://dane.biznes.gov.pl ("Dane po API") in `CEIDG_TOKEN`.
- **Limits:** 1000 requests per hour and 50 per 3 minutes; going over blocks the API for
  180 s. Requests are spaced 3.6 s apart and a 429 waits 185 s.
- **First import:** active businesses month by month of start date (from 1990; the first
  window includes everything older), details fetched in batches of 50 ids. Progress is saved
  after each month, so the multi-day import resumes after restarts.
- **Afterwards:** daily `/zmiana` (changes) in windows of at most 5 days. Businesses that
  stop being active or remove their phone are deleted.
- Only businesses with status `AKTYWNY` and a valid phone are kept.
- **Not yet verified against the live API** (needs a token): page numbering from 0, page and
  batch size 50, and the exact `telefon` format.
- Runs in its own `ceidg` container (`COMPOSE_PROFILES=ceidg`), not in `import all`.

## Parsing phone numbers from registers

`rpwdl` and `apteki` (and every new source) use `phone.find_numbers(text)`, which returns every valid number in free
text in order, without duplicates. On top of libphonenumber's matcher it understands two
habits of Polish registers:

- the old trunk zero before the area code: `071 327-02-02`, `(0-71) 123 45 67`;
- runs of spaces as a separator: `071 317-23-95  0606-795-234` → two numbers.

Text that is not a valid number (`999`, `21-040`, 7-digit local numbers) is ignored.

## Considered and not added

| Source | Why not |
|---|---|
| Schools (RSPO) | The open RSPO API was shut down on 2 March 2026; the new one (https://api.rspo.gov.pl) needs an access request by e-mail to rspo@cie.gov.pl. The yearly school list on dane.gov.pl has no phone numbers. |
| Individual medical practices (RPWDL) | Mostly private numbers. |
| sprawdzamnumer.pl and similar | Not evaluated yet: no official API is known, and reusing their user reports would need their permission. For now spam data comes from your own reports. |

## Adding a source

1. Create `sources/<name>.py` with `DEFAULT_DELAY` (seconds between requests) and
   `iter_records(ctx, client)` yielding `(source_id, OrganizationRecord | None)` for **every**
   entry the source currently lists. Use `fetch()` from `sources/__init__.py` for retries,
   `find_numbers()` for phones and `shorten_name()` for long legal names.
2. Register it in `importer.SOURCES`, and in `DEFAULT_SOURCES` if `import all` should run it
   (it then also gets an `import:<name>` check in `/status`).
3. Add a test with a small real sample of the source's data (see `tests/test_registers.py`)
   that checks the parsed records, including the entries that must be skipped.
4. Run a real import into a scratch database to check counts, time and labels:
   `DATABASE_URL=sqlite:////tmp/try.db uv run phone-blocker migrate && DATABASE_URL=sqlite:////tmp/try.db uv run phone-blocker import <name>`.
5. Add a row to the tables in this file and in `backend/README.md`.

The full contract, including incremental sources and `replace_all`, is in the docstring of
`sources/__init__.py`.
