# Phone Blocker

A personal unwanted-call blocker for iPhone, with its own backend.

- **Public directory ("yellow pages").** Every public number the backend can find in
  official Polish registers (city halls, courts, hospitals, clinics, pharmacies, …) gets a
  caller-ID label such as "Urząd Miejski Wrocławia" and is never blocked.
- **Unwanted calls.** Numbers reported as telemarketing, scam, debt collection, … (in the
  style of [sprawdzamnumer.pl](https://www.sprawdzamnumer.pl)) are labelled and blocked.
- **Your own lists.** Always-block, never-block and your own labels beat everything else.
- **Prefix rules and spoofing.** Block whole prefixes or countries, and block calls from
  Polish numbers that were never assigned to any operator (a sign of spoofed caller ID).

```diagram
┌──────────────────────┐   daily imports   ┌─────────────────────────────────┐
│ Public registers     │──────────────────▶│ Backend (FastAPI + PostgreSQL)  │
│ BIP, NFZ, RPWDL,     │                   │  • directory and reports        │
│ Rejestr Aptek, UKE,  │                   │  • /v1 API, /admin page         │
│ CEIDG (optional)     │                   │  • alerts, backups, /status     │
└──────────────────────┘                   └───────────────┬─────────────────┘
                                                           │ /v1/directory sync,
                                                           │ /v1/numbers lookups
                                                           ▼
                                           ┌─────────────────────────────────┐
                                           │ iPhone app (planned)            │
                                           │  Call Directory extension       │
                                           └─────────────────────────────────┘
```

## Status

| Part | State |
|------|-------|
| Backend | Working: 6 directory sources, reports, personal lists, prefix rules, admin page, Docker deployment with HTTPS, backups, monitoring, CI |
| iPhone app | Not started; the API it needs is in place ([sync contract](docs/api.md#syncing-the-iphone)) |

## Where to read next

| You want to… | Read |
|---|---|
| Run the backend locally or see every command | [backend/README.md](backend/README.md) |
| Understand how it works inside | [docs/architecture.md](docs/architecture.md) |
| Call the API (iPhone app, scripts) | [docs/api.md](docs/api.md) |
| Know what each data source imports | [docs/data-sources.md](docs/data-sources.md) |
| Put it on a server and keep it running | [docs/operations.md](docs/operations.md) |
| Change the code (humans and AI agents) | [docs/development.md](docs/development.md), [AGENTS.md](AGENTS.md) |
| Look up a term (BIP, UKE, RPWDL, E.164, …) | [docs/glossary.md](docs/glossary.md) |

## Repository layout

```
.
├── AGENTS.md                 Rules and map for AI coding agents
├── docs/                     Guides (architecture, API, sources, operations, development)
├── .github/workflows/        CI: tests on SQLite and PostgreSQL, Docker image check
└── backend/                  Python backend (FastAPI, SQLAlchemy, Alembic)
    ├── src/phone_blocker/    Application code
    ├── tests/                pytest suite
    ├── compose.yaml          Production stack
    └── README.md             Quick start and command reference
```
