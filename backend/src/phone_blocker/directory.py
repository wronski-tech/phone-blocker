"""Stores directory entries and turns listings and reports into each number's caller-ID state."""

import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .models import Listing, NumberRange, Organization, PhoneNumber, SyncState, utcnow


@dataclass
class ListedPhone:
    number: int  # E.164 digits without '+'
    kind: str  # "phone" or "fax"
    department: str | None = None


@dataclass
class OrganizationRecord:
    """An organization as one importer source describes it."""

    source_id: str
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
    phones: list[ListedPhone] = field(default_factory=list)


RECORD_FIELDS = ("name", "street", "postal_code", "city", "commune", "county",
                 "voivodeship", "website", "email", "nip", "regon")

# Report categories with the Polish wording shown as the caller-ID label.
SPAM_CATEGORIES = {
    "telemarketing": "Telemarketing",
    "scam": "Oszustwo",
    "debt_collection": "Windykacja",
    "survey": "Ankieta",
    "robocall": "Automat",
    "silent": "Głuchy telefon",
    "other": "Niechciany",
}
SAFE = "safe"
REPORT_CATEGORIES = (*SPAM_CATEGORIES, SAFE)
BLOCK, ALLOW = "block", "allow"  # personal actions


def get_or_create_phone(session: Session, number: int) -> PhoneNumber:
    phone = session.scalar(select(PhoneNumber).where(PhoneNumber.number == number))
    if phone is None:
        phone = PhoneNumber(number=number, label=None, blocked=False, version=0)
        session.add(phone)
    return phone


def save_record(session: Session, source: str, record: OrganizationRecord, block_threshold: int) -> Organization:
    """Insert or update an organization and its numbers, then refresh the affected numbers."""
    org = session.scalar(
        select(Organization).where(Organization.source == source, Organization.source_id == record.source_id)
    )
    if org is None:
        org = Organization(source=source, source_id=record.source_id)
        session.add(org)

    for name in RECORD_FIELDS:
        setattr(org, name, getattr(record, name))
    departments = dict.fromkeys(p.department for p in record.phones if p.department)
    org.search_text = fold(" ".join(filter(None, [record.name, record.city, record.commune, *departments])))
    org.fetched_at = utcnow()

    wanted = list(dict.fromkeys((p.number, p.kind, p.department) for p in record.phones))  # keep source order
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


def delete_organization(session: Session, org: Organization, block_threshold: int) -> None:
    phones = sorted({l.phone_number for l in org.listings}, key=lambda p: p.number)
    session.delete(org)
    for phone in phones:
        refresh_number(session, phone, block_threshold)


def refresh_number(session: Session, phone: PhoneNumber, block_threshold: int) -> None:
    """Recompute label/blocked and bump the sync version when they change.

    Precedence: the owner's personal settings, then public listings (never blocked,
    whatever the reports say), then spam reports. A personally allowed number is never
    blocked and gets no spam label.
    """
    session.flush()
    session.expire(phone, ["listings", "reports"])

    if phone.listings:
        best = min(phone.listings, key=lambda l: (l.kind != "phone", l.department is not None, l.id))
        label = best.organization.name
        if best.department:
            label += f" – {best.department}"
        if best.kind == "fax":
            label += " (faks)"
        blocked = False
    elif phone.personal_action == ALLOW:
        label, blocked = None, False
    else:
        spam = [r.category for r in phone.reports if r.category != SAFE]
        safe = len(phone.reports) - len(spam)
        label = None
        if len(spam) > safe:
            top = Counter(spam).most_common(1)[0][0]
            label = f"Spam: {SPAM_CATEGORIES[top]} ({len(spam)})"
        blocked = len(spam) - safe >= block_threshold

    if phone.personal_label:
        label = phone.personal_label
    if phone.personal_action == BLOCK:
        blocked = True
    label = label[:200] if label else None
    if (label, blocked) != (phone.label, phone.blocked):
        phone.label = label
        phone.blocked = blocked
        phone.version = _next_version(session)


def _next_version(session: Session) -> int:
    return session.execute(
        update(SyncState).where(SyncState.id == 1).values(version=SyncState.version + 1).returning(SyncState.version)
    ).scalar_one()


def find_range(session: Session, number: int) -> NumberRange | None:
    """The UKE range a Polish number belongs to (longest matching prefix)."""
    digits = str(number)
    if not digits.startswith("48"):  # country codes are prefix-free, so this means Poland
        return None
    national = digits[2:]
    prefixes = [national[:i] for i in range(1, len(national) + 1)]
    return session.scalar(
        select(NumberRange).where(NumberRange.prefix.in_(prefixes))
        .order_by(func.length(NumberRange.prefix).desc()).limit(1)
    )


def fold(text: str) -> str:
    """Lowercase and strip diacritics so "wroclaw" matches "Wrocław"."""
    text = text.lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
