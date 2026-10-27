# Operations

Running the backend on a server: deployment, configuration, updates, backups, monitoring and
troubleshooting. Commands run in `backend/` on the server unless noted.

## The production stack

`backend/compose.yaml`:

| Service | Image | Does |
|---|---|---|
| `db` | `postgres:17-alpine` | The database, in the `db-data` volume |
| `api` | built from `Dockerfile` | Runs `phone-blocker migrate`, then uvicorn on port 8000 |
| `importer` | same image | `phone-blocker import all --every-hours 24`: all default sources on start, then 24 h after each round ends |
| `ceidg` | same image | Optional (`COMPOSE_PROFILES=ceidg`): CEIDG import, daily |
| `backup` | `postgres:17-alpine` | `pg_dump` into `./backups` on start and every 24 h, keeps 14 |
| `caddy` | `caddy:2-alpine` | HTTPS with an automatic Let's Encrypt certificate for `DOMAIN`, HTTP → HTTPS redirect |

The importer and ceidg containers wait until the API is healthy, because the API container
applies database migrations.

## Requirements

- A Linux VPS with Docker and the Compose plugin. 2 GB RAM is enough (the largest import,
  RPWDL, peaks around 300 MB). A few GB of disk for the database and 14 backups.
- A domain (or subdomain) whose DNS A/AAAA record points at the server.
- Ports 80 and 443 open (80 is needed for the certificate challenge).

## Deploy

```sh
git clone https://github.com/wronski-tech/phone-blocker.git && cd phone-blocker/backend
cp .env.example .env          # then edit .env, see the table below
docker compose up -d --build  # the first import starts right away
docker compose ps             # api and db should be "healthy"
curl https://<DOMAIN>/health  # {"status":"ok"}
```

Open `https://<DOMAIN>/admin` and log in with any user name and `API_TOKEN` as the password.
The first full round of imports takes a few hours (BIP and NFZ are the slow ones); watch it
on the admin dashboard or with `docker compose logs -f importer`.

## Configuration (`backend/.env`)

| Variable | Required | Meaning |
|---|---|---|
| `DOMAIN` | yes | Public host name; Caddy requests its certificate |
| `POSTGRES_PASSWORD` | yes | Database password (`openssl rand -hex 32`) |
| `API_TOKEN` | yes | Bearer token for `/v1` and the admin password (`openssl rand -hex 32`) |
| `BLOCK_THRESHOLD` | no (1) | Net spam reports (spam − safe) needed to block a number |
| `NTFY_URL` | no | ntfy topic URL for push alerts, e.g. `https://ntfy.sh/phone-blocker-<random>` |
| `NTFY_TOKEN` | no | Bearer token for a protected or self-hosted ntfy topic |
| `CEIDG_TOKEN` | no | Enables the CEIDG source (with `COMPOSE_PROFILES=ceidg`) |
| `COMPOSE_PROFILES` | no | `ceidg` to start the CEIDG container |

Inside the containers the app also reads `DATABASE_URL` (set by compose) and `BACKUP_DIR`
(`/backups` in the API container, for the backup check). After changing `.env`, run
`docker compose up -d` to recreate the affected containers.

Never commit `.env`; it is ignored by git.

## Updating

```sh
git pull && docker compose up -d --build
```

New migrations run automatically when the API container starts. The database volume
survives rebuilds.

## Backups

Dumps are written to `backend/backups/phone_blocker-YYYYMMDD-HHMM.dump` (PostgreSQL custom
format, compressed). A failed dump sends an ntfy alert, and `/status` turns red when the
newest dump is older than 2 days.

**Copy them off the server.** A backup on the same disk does not survive losing the server.
For example, from another machine:

```sh
rsync -a user@server:phone-blocker/backend/backups/ ~/phone-blocker-backups/
```

**Restore:**

```sh
docker compose stop api importer
docker compose exec -T db pg_restore -U phone_blocker -d phone_blocker --clean --if-exists < backups/phone_blocker-YYYYMMDD-HHMM.dump
docker compose start api importer
```

**Manual backup now:** `docker compose restart backup` (it dumps on start).

## Monitoring

| Signal | How you notice |
|---|---|
| An import fails | ntfy push "Import <source> failed" with the error |
| An import would delete more than 10% of a source | ntfy push "Import <source> needs a look"; nothing was deleted |
| A backup fails | ntfy push "Backup failed" |
| A source has not imported for 3 days, or no backup for 2 days | `/status` returns 503 |
| The database is down | `/health` and `/status` return 503 |
| The whole server is down | Only an external monitor can tell |

Setup:

1. Install the ntfy app on your phone and subscribe to a topic name nobody can guess.
2. Set `NTFY_URL=https://ntfy.sh/<topic>` in `.env` and run `docker compose up -d`.
3. Add a free external HTTP monitor (UptimeRobot, Better Stack, healthchecks.io, …) for
   `https://<DOMAIN>/status`, alerting on any non-200 response.

The admin dashboard shows the same checks as `/status` at the top.

## Everyday tasks

| Task | Command |
|---|---|
| See recent import runs | `docker compose exec api phone-blocker runs` (or the admin dashboard) |
| Run one source now | `docker compose run --rm importer phone-blocker import nfz` |
| Import one BIP card | `docker compose run --rm importer phone-blocker import-bip-card <url>` |
| Follow logs | `docker compose logs -f api importer` |
| Open a database shell | `docker compose exec db psql -U phone_blocker` |
| Fix a wrong label | Admin → search the number → set your own label (imports never overwrite it) |
| Undo a mistaken report | Admin → Reports → Delete, or `DELETE /v1/reports/{id}` |
| Block a whole prefix | Admin → Rules, or `POST /v1/rules` |

## Troubleshooting

| Symptom | Check |
|---|---|
| `docker compose up` says "set … in .env" | A required variable in `.env` is empty. |
| HTTPS does not work | DNS points at the server? Ports 80/443 open? `docker compose logs caddy` shows the certificate attempts. |
| `api` not healthy | `docker compose logs api`: usually a database password mismatch or a failed migration. |
| An import keeps failing | Admin → Import runs → the run shows the error and traceback. Government APIs have outages; a single failed day is normal and keeps the existing data. A format change needs a code fix in `sources/<name>.py`. |
| "Refused to remove N of M entries" | The source suddenly lists far fewer entries. Check the register's website; if the drop is real, run the import once with a temporarily higher `MAX_REMOVED_SHARE` in `importer.py`. |
| `/status` red for `import:bip` after deploy | Normal until the first BIP round finishes (hours). |
| Numbers labelled wrongly | Look the number up in the admin page: "Listed by" shows which source and organization the label comes from. |
