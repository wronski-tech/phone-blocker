"""Pharmacies from the Rejestr Aptek (https://rejestry.ezdrowie.gov.pl/registry/ra).

The register publishes its full content as one spreadsheet, regenerated daily; one
download covers every pharmacy, pharmacy outlet and hospital pharmacy. Only active ones
are kept.
"""

from collections.abc import Iterator

import httpx
import xlrd

from ..directory import ListedPhone, OrganizationRecord
from ..phone import find_numbers
from . import ImportContext, fetch, shorten_name

EXPORT_URL = "https://rejestry.ezdrowie.gov.pl/api/ra/filegenerator/getxls"
DEFAULT_DELAY = 0  # a single request
ACTIVE = "AKTYWNA"
PREFIXES = {"PUNKT APTECZNY": "Punkt apteczny"}  # rodzaj_apteki -> label prefix; others "Apteka"


def iter_records(ctx: ImportContext, client: httpx.Client) -> Iterator[tuple[str, OrganizationRecord | None]]:
    content = fetch(client, EXPORT_URL, parse=lambda r: r.content)
    rows = parse_rows(content)
    ctx.log(f"Rejestr Aptek: {len(rows)} rows")
    for row in rows:
        if row["stan_apteki"] == ACTIVE and (record := to_record(row)):
            yield record.source_id, record


def parse_rows(content: bytes) -> list[dict[str, str]]:
    sheet = xlrd.open_workbook(file_contents=content).sheet_by_index(0)
    header = sheet.row_values(0)
    return [dict(zip(header, (str(v).strip() for v in sheet.row_values(i)))) for i in range(1, sheet.nrows)]


def to_record(row: dict[str, str]) -> OrganizationRecord | None:
    """None when the pharmacy published no valid phone number."""
    phones = [ListedPhone(n, "phone") for n in find_numbers(row["telefon"])]
    phones += [ListedPhone(n, "fax") for n in find_numbers(row["fax"])]
    if not phones:
        return None
    building = "/".join(filter(None, [row["numer_budynku"], row["numer_lokalu"]]))
    return OrganizationRecord(
        source_id=row["identyfikator_apteki"],
        name=_name(row),
        street=" ".join(filter(None, [row["nazwa_ulicy"] and row["typ_ulicy"], row["nazwa_ulicy"], building])) or None,
        postal_code=row["kod_pocztowy"] or None,
        city=row["miejscowosc"] or None,
        commune=row["gmina"] or None,
        county=row["powiat"] or None,
        voivodeship=row["wojewodztwo"].capitalize() or None,
        website=row["adres_www"] or None,
        email=row["email"] or None,
        nip=row["wlasciciel_nip"] or None,
        regon=row["wlasciciel_regon"] or None,
        phones=phones,
    )


def _name(row: dict[str, str]) -> str:
    """'ARNIKA' -> 'Apteka ARNIKA'; unnamed pharmacies are called after their owner."""
    name = shorten_name(row["nazwa_apteki"] or row["wlasciciel_nazwa"])
    prefix = PREFIXES.get(row["rodzaj_apteki"], "Apteka")
    if any(word in name.lower() for word in ("aptek", "apteczny")):
        return name
    return f"{prefix} {name}".strip()
