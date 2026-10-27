"""Public institutions listed in the Polish BIP (gov.pl/web/bip).

Discovery uses the JSON tree behind https://www.gov.pl/web/bip/spis-podmiotow;
each institution's phone numbers come from its HTML contact card, e.g.
https://www.gov.pl/web/bip/urzad-miejski-wroclawia-dolnoslaskie-wroclaw-wroclaw
"""

import re
import time
from collections import deque
from collections.abc import Iterator

import httpx
import phonenumbers
from bs4 import BeautifulSoup

from ..directory import ListedPhone, OrganizationRecord
from ..phone import REGION, to_int
from . import ImportContext, fetch

CARD_BASE_URL = "https://www.gov.pl/web/bip"
TREE_API_URL = "https://aplikacje.gov.pl/app/bip-back/api/subjects"
MAIN_SECTION = "Dane podmiotu"
DEFAULT_DELAY = 0.5


def parse_card(html: str, url: str) -> OrganizationRecord:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("div.contact-card")
    if root is None or root.h2 is None:
        raise ValueError("Page has no BIP contact card")

    card = OrganizationRecord(source_id=url, name=root.h2.get_text(strip=True))
    postal_city = None
    section = None
    for el in root.find_all(["h3", "a", "ul"], recursive=False):
        if el.name == "h3":
            section = el.get_text(strip=True)
        elif el.name == "a" and section == "Strona BIP":
            card.website = el.get("href")
        elif el.name == "ul" and "visits" not in el.get("class", []):
            for li in el.find_all("li", recursive=False):
                text = " ".join(li.get_text(" ", strip=True).split())
                key, sep, value = (part.strip() for part in text.partition(":"))
                key = key.lower()
                if sep and key.startswith(("telefon", "tel", "faks", "fax")):
                    kind = "fax" if key.startswith(("faks", "fax")) else "phone"
                    department = None if section == MAIN_SECTION else section
                    for match in phonenumbers.PhoneNumberMatcher(value, REGION):
                        card.phones.append(ListedPhone(to_int(match.number), kind, department))
                elif section != MAIN_SECTION:
                    continue  # skip editor names and e-mails
                elif not sep:
                    if m := re.fullmatch(r"(\d{2}-\d{3})\s+(.+)", text):
                        card.postal_code, postal_city = m.groups()
                    else:
                        card.street = text
                elif key == "województwo":
                    card.voivodeship = value
                elif key == "powiat":
                    card.county = value
                elif key == "gmina":
                    card.commune = value
                elif key == "miejscowość":
                    card.city = value
                elif key == "e-mail":
                    card.email = value
                elif key == "nip":
                    card.nip = value
                elif key == "regon":
                    card.regon = value
    card.city = card.city or postal_city
    return card


def fetch_card(client: httpx.Client, url: str) -> OrganizationRecord:
    return parse_card(fetch(client, url), url)


def iter_records(ctx: ImportContext, client: httpx.Client) -> Iterator[tuple[str, OrganizationRecord | None]]:
    for subject in _iter_subjects(client, ctx.delay):
        url = CARD_BASE_URL + subject["url"]
        if ctx.is_fresh(url):
            yield url, None
            continue
        try:
            yield url, fetch_card(client, url)
        except (httpx.HTTPError, ValueError) as exc:
            ctx.error(f"skip {url}: {exc}")
            yield url, None
        time.sleep(ctx.delay)


def _iter_subjects(client: httpx.Client, delay: float) -> Iterator[dict]:
    """Walk the BIP tree breadth-first and yield institutions that have a contact card."""
    queue: deque[int | None] = deque([None])
    seen: set[int] = set()
    while queue:
        parent_id = queue.popleft()
        params = {"archive": "false"} | ({"parentId": parent_id} if parent_id else {})
        for node in fetch(client, TREE_API_URL, params, parse=lambda r: r.json()["list"]):
            if node["id"] in seen:
                continue
            seen.add(node["id"])
            if node.get("childCount"):
                queue.append(node["id"])
            if node.get("type") == "SUBJECT" and node.get("hasContactCard") and node.get("url"):
                yield node
        time.sleep(delay)
