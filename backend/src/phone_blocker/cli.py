import argparse
import logging
from datetime import timedelta

import httpx

from . import bip
from .config import Settings
from .db import make_sessionmaker, migrate


def main() -> None:
    parser = argparse.ArgumentParser(prog="phone-blocker")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="Create or upgrade the database schema")

    crawl = commands.add_parser("crawl-bip", help="Import all public institutions from gov.pl BIP")
    crawl.add_argument("--limit", type=int, help="Stop after saving this many cards")
    crawl.add_argument("--delay", type=float, default=0.5, help="Seconds between requests (default 0.5)")
    crawl.add_argument("--max-age-days", type=float, default=7, help="Skip cards refreshed more recently")

    card = commands.add_parser("import-bip-card", help="Import specific BIP contact card URLs")
    card.add_argument("urls", nargs="+")

    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "migrate":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        migrate(settings.database_url)
        return
    sessions = make_sessionmaker(settings.database_url)

    if args.command == "crawl-bip":
        saved = bip.crawl(
            sessions,
            settings.block_threshold,
            limit=args.limit,
            max_age=timedelta(days=args.max_age_days),
            delay=args.delay,
        )
        print(f"Saved {saved} contact cards")
    elif args.command == "import-bip-card":
        with httpx.Client(headers={"User-Agent": bip.USER_AGENT}, timeout=30, follow_redirects=True) as client:
            for url in args.urls:
                response = client.get(url)
                response.raise_for_status()
                parsed = bip.parse_card(response.text)
                with sessions.begin() as session:
                    bip.save_card(session, url, parsed, settings.block_threshold)
                print(f"{parsed.name}: {len(parsed.phones)} numbers")


if __name__ == "__main__":
    main()
