"""Clinics and hospital departments with an NFZ contract.

Uses the public NFZ "Terminy leczenia" API (https://api.nfz.gov.pl/app-itl-api/), which lists
every queue with its provider, place (department or clinic), address and phone number.
Rows repeat per medical service, so they are grouped into one organization per place.
"""

import time
from collections.abc import Iterator

import httpx
import phonenumbers

from ..directory import ListedPhone, OrganizationRecord
from ..phone import REGION, to_int
from . import ImportContext, fetch

QUEUES_URL = "https://api.nfz.gov.pl/app-itl-api/queues"
PAGE_SIZE = 25  # the API's maximum
DEFAULT_DELAY = 0.3
PROVINCES = {
    "01": "Dolnośląskie", "02": "Kujawsko-pomorskie", "03": "Lubelskie", "04": "Lubuskie",
    "05": "Łódzkie", "06": "Małopolskie", "07": "Mazowieckie", "08": "Opolskie",
    "09": "Podkarpackie", "10": "Podlaskie", "11": "Pomorskie", "12": "Śląskie",
    "13": "Świętokrzyskie", "14": "Warmińsko-mazurskie", "15": "Wielkopolskie", "16": "Zachodniopomorskie",
}
ABBREVIATIONS = {
    "SAMODZIELNY PUBLICZNY ZAKŁAD OPIEKI ZDROWOTNEJ": "SP ZOZ",
    "NIEPUBLICZNY ZAKŁAD OPIEKI ZDROWOTNEJ": "NZOZ",
    "SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ": "SP. Z O.O.",
    "SPÓŁKA AKCYJNA": "S.A.",
}


def iter_records(ctx: ImportContext, client: httpx.Client) -> Iterator[tuple[str, OrganizationRecord | None]]:
    # Grouped per province: a failure mid-way keeps the provinces already saved.
    for code, province in PROVINCES.items():
        places: dict[str, OrganizationRecord] = {}
        for row in _iter_rows(client, code, ctx.delay):
            record = places.get(source_id := _source_id(code, row))
            if record is None:
                record = places[source_id] = OrganizationRecord(
                    source_id=source_id,
                    name=_shorten(row["provider"].strip()),
                    street=row.get("address"),
                    city=row.get("locality"),
                    voivodeship=province,
                    nip=row.get("nip-provider"),
                    regon=row.get("regon-provider"),
                )
            place = (row.get("place") or "").strip()
            department = place if place and place != row["provider"].strip() else None
            for match in phonenumbers.PhoneNumberMatcher(row.get("phone") or "", REGION):
                record.phones.append(ListedPhone(to_int(match.number), "phone", department))
        ctx.log(f"NFZ {province}: {len(places)} places")
        yield from places.items()


def _shorten(name: str) -> str:
    """Use the usual abbreviations so caller ID shows the distinctive part of the name."""
    for long, short in ABBREVIATIONS.items():
        name = name.replace(long, short)
    return name


def _source_id(province: str, row: dict) -> str:
    return "/".join([province, row["provider-code"], row.get("place") or "", row.get("address") or "",
                     row.get("locality") or ""])


def _iter_rows(client: httpx.Client, province: str, delay: float) -> Iterator[dict]:
    page = 1
    while True:
        body = fetch(client, QUEUES_URL, {
            "page": page, "limit": PAGE_SIZE, "format": "json", "case": 1,
            "province": province, "api-version": "1.3",
        }, parse=lambda r: r.json())
        for item in body["data"]:
            yield item["attributes"]
        if not body["data"] or page * PAGE_SIZE >= body["meta"]["count"]:
            return
        page += 1
        time.sleep(delay)
