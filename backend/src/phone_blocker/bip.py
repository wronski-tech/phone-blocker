"""Importer for public institutions listed in the Polish BIP (gov.pl/web/bip).

Discovery uses the JSON tree behind https://www.gov.pl/web/bip/spis-podmiotow;
each institution's phone numbers come from its HTML contact card, e.g.
https://www.gov.pl/web/bip/urzad-miejski-wroclawia-dolnoslaskie-wroclaw-wroclaw
"""

import re
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta

import httpx
import phonenumbers
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .directory import fold, get_or_create_phone, refresh_number
from .models import Listing, Organization, utcnow
from .phone import REGION, to_int

CARD_BASE_URL = "https://www.gov.pl/web/bip"
TREE_API_URL = "https://aplikacje.gov.pl/app/bip-back/api/subjects"
USER_AGENT = "phone-blocker/0.1 (personal public phone directory)"
MAIN_SECTION = "Dane podmiotu"


@dataclass
class CardPhone:
    number: int
    kind: str  # "phone" or "fax"
    department: str | None


@dataclass
class Card:
    name: str
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    commune: str | None = None
    county: str | None = None
    voivodeship: str | None = None
    website: str | None = None
    email: str | None = None
    nip: str | None = None
    regon: str | None = None
    phones: list[CardPhone] = field(default_factory=list)


def parse_card(html: str) -> Card:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("div.contact-card")
    if root is None or root.h2 is None:
        raise ValueError("Page has no BIP contact card")

    card = Card(name=root.h2.get_text(strip=True))
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
                        card.phones.append(CardPhone(to_int(match.number), kind, department))
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


def save_card(session: Session, url: str, card: Card, block_threshold: int) -> Organization:
    """Insert or update an organization and its numbers, then refresh affected numbers."""
    org = session.scalar(select(Organization).where(Organization.source_url == url))
    if org is None:
        org = Organization(source="bip", source_url=url)
        session.add(org)

    for name in ("name", "street", "postal_code", "city", "commune", "county",
                 "voivodeship", "website", "email", "nip", "regon"):
        setattr(org, name, getattr(card, name))
    org.search_text = fold(" ".join(filter(None, [card.name, card.city, card.commune])))
    org.fetched_at = utcnow()

    wanted = list(dict.fromkeys((p.number, p.kind, p.department) for p in card.phones))  # keep card order
    current = {(l.phone_number.number, l.kind, l.department): l for l in org.listings}
    affected = {l.phone_number for l in org.listings}  # all of them: the name may have changed
    for key, listing in current.items():
        if key not in wanted:
            org.listings.remove(listing)
    for number, kind, department in (key for key in wanted if key not in current):
        phone = get_or_create_phone(session, number)
        org.listings.append(Listing(phone_number=phone, kind=kind, department=department))
        affected.add(phone)

    for phone in sorted(affected, key=lambda p: p.number):
        refresh_number(session, phone, block_threshold)
    return org


def iter_subjects(client: httpx.Client, delay: float) -> Iterator[dict]:
    """Walk the BIP tree breadth-first and yield institutions that have a contact card."""
    queue: deque[int | None] = deque([None])
    seen: set[int] = set()
    while queue:
        parent_id = queue.popleft()
        params = {"archive": "false"} | ({"parentId": parent_id} if parent_id else {})
        response = client.get(TREE_API_URL, params=params)
        response.raise_for_status()
        for node in response.json()["list"]:
            if node["id"] in seen:
                continue
            seen.add(node["id"])
            if node.get("childCount"):
                queue.append(node["id"])
            if node.get("type") == "SUBJECT" and node.get("hasContactCard") and node.get("url"):
                yield node
        time.sleep(delay)


def crawl(
    sessions: sessionmaker[Session],
    block_threshold: int,
    *,
    limit: int | None = None,
    max_age: timedelta = timedelta(days=7),
    delay: float = 0.5,
    log: Callable[[str], None] = print,
) -> int:
    """Import every BIP contact card not refreshed within `max_age`. Returns cards saved."""
    with sessions() as session:
        fresh = set(session.scalars(
            select(Organization.source_url).where(Organization.fetched_at >= utcnow() - max_age)
        ))

    saved = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        for subject in iter_subjects(client, delay):
            url = CARD_BASE_URL + subject["url"]
            if url in fresh:
                continue
            try:
                response = client.get(url)
                response.raise_for_status()
                card = parse_card(response.text)
            except (httpx.HTTPError, ValueError) as exc:
                log(f"skip {url}: {exc}")
                continue
            with sessions.begin() as session:
                save_card(session, url, card, block_threshold)
            saved += 1
            log(f"[{saved}] {card.name}: {len(card.phones)} numbers")
            if limit and saved >= limit:
                break
            time.sleep(delay)
    return saved
