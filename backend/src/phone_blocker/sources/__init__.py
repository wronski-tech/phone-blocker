"""Directory importers.

Each source module provides `DEFAULT_DELAY` and `iter_records(ctx, client)`, which yields
`(source_id, record)` for every organization the source currently lists. `record` is
None when the existing entry should be kept as is: it was refreshed recently, or
fetching it failed. Every listed id must be yielded, because after a complete run the
importer removes entries whose id was not seen.

Reference data that is simply replaced on every run (UKE number ranges) provides
`replace_all(session, client, ctx)` instead, returning the number of rows written.

Incremental sources (CEIDG) set `INCREMENTAL = True`. Their `iter_records` yields only
what changed, with `record` None meaning "remove this entry", so no cleanup runs after
them. They keep their progress in `ctx.state` and call `ctx.checkpoint()` to save it,
so a run that takes days continues where it stopped.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

USER_AGENT = "phone-blocker/0.1 (personal public phone directory)"


MAX_LOGGED_ERRORS = 200
NAME_ABBREVIATIONS = {
    "SAMODZIELNY PUBLICZNY ZAKŁAD OPIEKI ZDROWOTNEJ": "SP ZOZ",
    "SAMODZIELNY PUBLICZNY ZESPÓŁ ZAKŁADÓW OPIEKI ZDROWOTNEJ": "SP ZZOZ",
    "NIEPUBLICZNY ZAKŁAD OPIEKI ZDROWOTNEJ": "NZOZ",
    "SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ": "SP. Z O.O.",
    "SPÓŁKA AKCYJNA": "S.A.",
}


@dataclass
class ImportContext:
    delay: float
    log: Callable[[str], None] = print
    fresh_ids: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)  # first MAX_LOGGED_ERRORS, kept on the run
    error_count: int = 0
    state: dict = field(default_factory=dict)  # incremental sources: progress kept between runs
    checkpoint: Callable[[], None] = lambda: None  # saves `state`

    def is_fresh(self, source_id: str) -> bool:
        return source_id in self.fresh_ids

    def error(self, message: str) -> None:
        self.error_count += 1
        if len(self.errors) < MAX_LOGGED_ERRORS:
            self.errors.append(message)
        self.log(message)


class _Retryable(Exception):
    pass


def fetch(
    client: httpx.Client,
    url: str,
    params: dict | None = None,
    parse: Callable[[httpx.Response], Any] = lambda r: r.text,
    attempts: int = 5,
) -> Any:
    """GET and parse, retrying network errors, 429, 5xx and unparseable bodies.

    Government APIs hiccup often; e.g. the NFZ API occasionally returns a non-JSON page.
    Other 4xx responses raise immediately.
    """
    for attempt in range(attempts):
        try:
            response = client.get(url, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                raise _Retryable(f"HTTP {response.status_code} from {response.url}")
            response.raise_for_status()
            return parse(response)
        except (httpx.TransportError, _Retryable, ValueError):
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt * 2)
    raise AssertionError("unreachable")


def shorten_name(name: str) -> str:
    """Use the usual abbreviations, whatever the case, so caller ID shows the distinctive part."""
    for long, short in NAME_ABBREVIATIONS.items():
        name = re.sub(re.escape(long), short, name, flags=re.IGNORECASE)
    return " ".join(name.replace('""', '"').split())
