"""Healthcare providers from the RPWDL register (https://rpwdl2.ezdrowie.gov.pl).

Every hospital, clinic, practice company and other healthcare provider ("podmiot
leczniczy") with its facilities ("zakłady"), their organisational units ("jednostki") and
departments ("komórki"), each with its own phone number. The register publishes all of it
as one daily ZIP of CSV files. Individual doctors' and nurses' practices are in other files
and are left out: they are mostly private numbers.

One organization per provider. A number listed for the provider itself has no department;
a number listed only further down gets the name of the unit it belongs to, taken from the
highest level it appears at, unless several units at that level share it.
"""

import csv
import io
import zipfile
from collections import defaultdict
from collections.abc import Iterator

import httpx

from ..directory import ListedPhone, OrganizationRecord
from ..phone import find_numbers
from . import ImportContext, fetch, shorten_name

EXPORT_URL = ("https://rpwdl2.ezdrowie.gov.pl/api/rpwdl-public-resource/ledgers-zip/initial"
              "?fileTypeInsideZip=CSV&activityType=HEALTHCARE_PROVIDER&activeLedgers=true")
DEFAULT_DELAY = 0  # a single request
NULL = "NULL"
# File, its name column and its end-of-activity column, from the provider down.
UNITS = [
    ("zaklady.csv", "Nazwa", "Data zakończenia działalności"),
    ("jednostki.csv", "Nazwa", "Data zakończenia działalności JO"),
    ("komorki.csv", "Nazwa komórki", "Data zakończenia działalności komórki"),
]


def iter_records(ctx: ImportContext, client: httpx.Client) -> Iterator[tuple[str, OrganizationRecord | None]]:
    archive = zipfile.ZipFile(io.BytesIO(fetch(client, EXPORT_URL, parse=lambda r: r.content)))
    records = parse(archive)
    ctx.log(f"RPWDL: {len(records)} providers with a phone number")
    for record in records:
        yield record.source_id, record


def parse(archive: zipfile.ZipFile) -> list[OrganizationRecord]:
    records: dict[str, OrganizationRecord] = {}
    for row in _rows(archive, "podmioty.csv"):
        if row["Data wykreślenia z rejestru"] != NULL or row["Data zakończenia działalności"] != NULL:
            continue
        records[row["ID Księgi"]] = OrganizationRecord(
            source_id=row["ID Księgi"],
            name=shorten_name(row["Nazwa"]),
            street=" ".join(_values(row["Ulica"], "/".join(_values(row["Budynek"], row["Lokal"])))) or None,
            postal_code=_value(row["Kod pocztowy"]),
            city=_value(row["Miejscowość"]),
            website=_value(row["Strona WWW"]),
            email=_value(row["Email"]),
            nip=_value(row["NIP"]),
            regon=_value(row["REGON"]),
            phones=[ListedPhone(n, "phone") for n in find_numbers(_value(row["Telefon"]) or "")],
        )

    # For each provider: number -> unit names at the highest level that lists it.
    unit_phones: dict[str, dict[int, set[str]]] = defaultdict(dict)
    for file, name_column, end_column in UNITS:
        level: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
        for row in _rows(archive, file):
            book = row["ID Księgi"]
            if book in records and row[end_column] == NULL:
                for number in find_numbers(_value(row["Telefon"]) or ""):
                    level[book][number].add(shorten_name(row[name_column]))
        for book, numbers in level.items():
            for number, names in numbers.items():
                unit_phones[book].setdefault(number, names)

    for book, numbers in unit_phones.items():
        record = records[book]
        listed = {p.number for p in record.phones}
        for number, names in numbers.items():
            if number not in listed:
                name = next(iter(names)) if len(names) == 1 else None
                department = name if name and name.lower() != record.name.lower() else None
                record.phones.append(ListedPhone(number, "phone", department and department[:200]))
    return [r for r in records.values() if r.phones]


def _rows(archive: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with archive.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""), delimiter=";")


def _value(text: str) -> str | None:
    text = text.strip()
    return None if text in ("", NULL) else text


def _values(*texts: str) -> list[str]:
    return [t for t in map(_value, texts) if t]
