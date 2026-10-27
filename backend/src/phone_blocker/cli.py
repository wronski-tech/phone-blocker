import argparse
import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import select

from .config import Settings
from .db import make_sessionmaker, migrate
from .directory import save_record
from .importer import SOURCES, run_import
from .models import ImportRun
from .sources import USER_AGENT, bip


def main() -> None:
    parser = argparse.ArgumentParser(prog="phone-blocker")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="Create or upgrade the database schema")

    imp = commands.add_parser("import", help="Import directory sources")
    imp.add_argument("sources", nargs="+", choices=[*SOURCES, "all"])
    imp.add_argument("--limit", type=int, help="Stop each source after saving this many entries (skips cleanup)")
    imp.add_argument("--delay", type=float, help="Seconds between requests (default depends on the source)")
    imp.add_argument("--max-age-days", type=float, default=7,
                     help="BIP: skip cards refreshed more recently (default 7)")
    imp.add_argument("--every-hours", type=float,
                     help="Keep running: repeat the import this many hours after each round ends")

    card = commands.add_parser("import-bip-card", help="Import specific BIP contact card URLs")
    card.add_argument("urls", nargs="+")

    commands.add_parser("runs", help="Show recent import runs")

    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "migrate":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        migrate(settings.database_url)
        return
    sessions = make_sessionmaker(settings.database_url)

    if args.command == "import":
        sources = list(SOURCES) if "all" in args.sources else args.sources
        while True:
            for source in sources:
                run_import(sessions, source, settings.block_threshold, limit=args.limit,
                           max_age=timedelta(days=args.max_age_days), delay=args.delay)
            if not args.every_hours:
                break
            print(f"Next import in {args.every_hours} h", flush=True)
            time.sleep(args.every_hours * 3600)
    elif args.command == "import-bip-card":
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
            for url in args.urls:
                record = bip.fetch_card(client, url)
                with sessions.begin() as session:
                    save_record(session, "bip", record, settings.block_threshold)
                print(f"{record.name}: {len(record.phones)} numbers")
    elif args.command == "runs":
        with sessions() as session:
            for run in session.scalars(select(ImportRun).order_by(ImportRun.id.desc()).limit(20)):
                print(f"{run.started_at:%Y-%m-%d %H:%M} {run.source:<5} {run.status:<8} saved={run.saved} "
                      f"removed={run.removed} errors={run.errors} {run.message or ''}")


if __name__ == "__main__":
    main()
