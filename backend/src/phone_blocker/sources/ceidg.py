"""Sole traders from CEIDG with the phone number they published.

Uses the CEIDG data warehouse API v3 (https://dane.biznes.gov.pl), which needs a free JWT
token in CEIDG_TOKEN. Only the details call returns phone numbers, and the API allows
1000 requests per hour, so:

1. The first import lists active businesses month by month of their start date (keeping
   every query small) and fetches details in batches. With about 2.6 million active
   businesses this takes days; progress is checkpointed after each month, so restarts
   continue where they stopped.
2. Afterwards each run only fetches businesses changed since the previous run (/zmiana).

Businesses that are no longer active or publish no phone number are left out (or removed).
"""

import os
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import httpx
import phonenumbers

from ..directory import ListedPhone, OrganizationRecord
from ..phone import REGION, to_int
from . import ImportContext

API_URL = "https://dane.biznes.gov.pl/api/ceidg/v3"
INCREMENTAL = True
DEFAULT_DELAY = 3.6  # the documented spacing that stays within 50 requests / 3 min and 1000 / h
PAGE_SIZE = 50
BATCH_SIZE = 50  # ids per details request
PENALTY_SECONDS = 185  # going over the limit blocks the API for 180 s from the last request
FIRST_MONTH = date(1990, 1, 1)  # the first window also covers everything older
CHANGES_WINDOW = timedelta(days=5)  # the API recommends at most 5 days per /zmiana query


def iter_records(ctx: ImportContext, client: httpx.Client) -> Iterator[tuple[str, OrganizationRecord | None]]:
    token = os.environ.get("CEIDG_TOKEN")
    if not token:
        raise RuntimeError("Set CEIDG_TOKEN (free JWT token from https://dane.biznes.gov.pl)")
    api = _Api(client, token, ctx.delay)
    state = ctx.state

    if not state.get("full_import_done"):
        # Changes made while the first import runs are picked up by the next incremental run.
        state.setdefault("changes_since", _now())
        month = date.fromisoformat(state.get("next_month", FIRST_MONTH.isoformat()))
        while month <= date.today():
            following = (month + timedelta(days=32)).replace(day=1)
            start = "1900-01-01" if month == FIRST_MONTH else month.isoformat()
            ids = api.list_ids(start, (following - timedelta(days=1)).isoformat())
            yield from _details(api, ids)
            state["next_month"] = following.isoformat()
            ctx.checkpoint()
            ctx.log(f"CEIDG: businesses started up to {month:%Y-%m} done")
            month = following
        state["full_import_done"] = True
        ctx.checkpoint()

    since = datetime.fromisoformat(state["changes_since"])
    now = datetime.fromisoformat(_now())
    while since < now:
        until = min(since + CHANGES_WINDOW, now)
        yield from _details(api, api.changed_ids(since, until))
        state["changes_since"] = until.isoformat(sep=" ")
        ctx.checkpoint()
        since = until


def to_record(firm: dict) -> OrganizationRecord | None:
    """None unless the business is active and published a valid phone number."""
    if firm.get("status") != "AKTYWNY":
        return None
    phones = [ListedPhone(to_int(m.number), "phone")
              for m in phonenumbers.PhoneNumberMatcher(firm.get("telefon") or "", REGION)]
    if not phones:
        return None
    address = firm.get("adresDzialalnosci") or {}
    owner = firm.get("wlasciciel") or {}
    building = "/".join(filter(None, [address.get("budynek"), address.get("lokal")]))
    return OrganizationRecord(
        source_id=firm["id"].upper(),  # /firmy lists ids in upper case, /zmiana in lower case
        name=firm["nazwa"].strip(),
        street=" ".join(filter(None, [address.get("ulica"), building])) or None,
        postal_code=address.get("kod"),
        city=address.get("miasto"),
        commune=address.get("gmina"),
        county=address.get("powiat"),
        voivodeship=(address.get("wojewodztwo") or "").capitalize() or None,
        website=firm.get("www"),
        email=firm.get("email"),
        nip=owner.get("nip"),
        regon=owner.get("regon"),
        phones=phones,
    )


def _details(api: "_Api", ids: list[str]) -> Iterator[tuple[str, OrganizationRecord | None]]:
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i:i + BATCH_SIZE]
        found = {firm["id"].upper(): firm for firm in api.firms(batch)}
        for firm_id in map(str.upper, batch):
            firm = found.get(firm_id)
            yield firm_id, (to_record(firm) if firm else None)


def _now() -> str:
    # The server's local time; any offset from the API's clock only shifts the windows,
    # since each run starts exactly where the previous one ended.
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


class _Api:
    """Requests spaced by `delay`, waiting out the API's 180 s penalty on 429."""

    def __init__(self, client: httpx.Client, token: str, delay: float):
        self.client, self.delay, self.last = client, delay, 0.0
        self.headers = {"Authorization": f"Bearer {token}"}

    def get(self, path: str, params: dict) -> dict | None:
        """JSON body, or None for 204 (no data)."""
        for attempt in range(6):
            time.sleep(max(0.0, self.last + self.delay - time.monotonic()))
            self.last = time.monotonic()
            try:
                response = self.client.get(f"{API_URL}/{path}", params=params, headers=self.headers)
            except httpx.TransportError:
                if attempt == 5:
                    raise
                time.sleep(30)
                continue
            if response.status_code == 429:
                time.sleep(PENALTY_SECONDS)
            elif response.status_code >= 500 and attempt < 5:
                time.sleep(30)
            elif response.status_code == 204:
                return None
            else:
                response.raise_for_status()
                return response.json()
        response.raise_for_status()
        raise RuntimeError(f"CEIDG API kept failing: HTTP {response.status_code}")

    def list_ids(self, start: str, end: str) -> list[str]:
        """Ids of active businesses that started between `start` and `end` (inclusive)."""
        ids: list[str] = []
        page = 0
        while body := self.get("firmy", {"status": "AKTYWNY", "dataod": start, "datado": end,
                                         "limit": PAGE_SIZE, "page": page}):
            ids += [firm["id"] for firm in body.get("firmy", [])]
            if len(body.get("firmy", [])) < PAGE_SIZE or len(ids) >= body.get("count", 0):
                break
            page += 1
        return ids

    def changed_ids(self, since: datetime, until: datetime) -> list[str]:
        ids: list[str] = []
        page = 0
        params = {"dataod": since.isoformat(sep=" "), "datado": until.isoformat(sep=" "), "limit": 500}
        while body := self.get("zmiana", params | {"page": page}):
            # The documentation spells the key both ways.
            batch = body.get("identyfikatoryWpisow") or body.get("indetyfikatoryWpisow") or []
            ids += batch
            if len(batch) < 500 or len(ids) >= body.get("count", 0):
                break
            page += 1
        return ids

    def firms(self, ids: list[str]) -> list[dict]:
        body = self.get("firma", {"ids": ids})
        return body.get("firma", []) if body else []
