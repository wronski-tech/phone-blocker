"""Polish numbering plan allocations from UKE (https://numeracja.uke.gov.pl).

Says which operator each number range was assigned to (landline, mobile, VoIP, 70x/80x).
Mobile numbers can be ported, so for them this is the original operator. Unlike the
directory sources this replaces the whole `number_ranges` table on every run.
"""

import csv
import io
import re
import time

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import NumberRange
from . import ImportContext, fetch

EXPORT_URL = "https://numeracja.uke.gov.pl/pl/{table}_tables/export.csv"
TABLES = {"pstn": "landline", "plmn": "mobile", "voip": "voip", "ndin": "service"}
DEFAULT_DELAY = 1.0
FIRST_RESERVE_ID = 99990  # operator ids from here up are UKE reserves, e.g. "Rezerwa Prezesa UKE"
RANGE = re.compile(r"(\d+)(?:\((.+)\))?")


def expand(spec: str) -> list[str]:
    """'121(0,3-5)' -> ['1210', '1213', '1214', '1215']."""
    base, alternatives = RANGE.fullmatch(spec).groups()
    if not alternatives:
        return [base]
    digits: list[str] = []
    for part in alternatives.split(","):
        low, _, high = part.partition("-")
        digits += [str(d) for d in range(int(low), int(high or low) + 1)]
    return [base + d for d in digits]


def parse_table(text: str, kind: str) -> list[NumberRange]:
    ranges = []
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        for prefix in expand(row["Zakres (number)"].strip()):
            ranges.append(NumberRange(
                prefix=prefix,
                kind=kind,
                operator=row["Operator (nazwa)"].strip(),
                operator_id=int(row["Operator (ID)"]),
                zone=row.get("Strefa (nazwa)") or None,
                service=row.get("Nazwa typu usługi") or None,
            ))
    return ranges


def replace_all(session: Session, client: httpx.Client, ctx: ImportContext) -> int:
    ranges = []
    for table, kind in TABLES.items():
        text = fetch(client, EXPORT_URL.format(table=table), parse=lambda r: r.content.decode("cp1250"))
        ranges += parse_table(text, kind)
        ctx.log(f"UKE {table}: {len(ranges)} prefixes so far")
        time.sleep(ctx.delay)
    session.execute(delete(NumberRange))
    session.add_all(ranges)
    return len(ranges)
