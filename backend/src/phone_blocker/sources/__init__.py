"""Directory importers.

Each source module provides `DEFAULT_DELAY` and `iter_records(ctx, client)`, which yields
`(source_id, record)` for every organization the source currently lists. `record` is
None when the existing entry should be kept as is: it was refreshed recently, or
fetching it failed. Every listed id must be yielded, because after a complete run the
importer removes entries whose id was not seen.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

USER_AGENT = "phone-blocker/0.1 (personal public phone directory)"


@dataclass
class ImportContext:
    delay: float
    log: Callable[[str], None] = print
    fresh_ids: set[str] = field(default_factory=set)
    errors: int = 0

    def is_fresh(self, source_id: str) -> bool:
        return source_id in self.fresh_ids

    def error(self, message: str) -> None:
        self.errors += 1
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
