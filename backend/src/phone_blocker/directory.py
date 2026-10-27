"""Turns listings and reports into the caller-ID label and block flag of each number."""

import unicodedata
from collections import Counter

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import PhoneNumber, SyncState

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


def get_or_create_phone(session: Session, number: int) -> PhoneNumber:
    phone = session.scalar(select(PhoneNumber).where(PhoneNumber.number == number))
    if phone is None:
        phone = PhoneNumber(number=number, label=None, blocked=False, version=0)
        session.add(phone)
    return phone


def refresh_number(session: Session, phone: PhoneNumber, block_threshold: int) -> None:
    """Recompute label/blocked and bump the sync version when they change.

    A number published by an organization is never blocked, whatever its reports say.
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
    else:
        spam = [r.category for r in phone.reports if r.category != SAFE]
        safe = len(phone.reports) - len(spam)
        label = None
        if len(spam) > safe:
            top = Counter(spam).most_common(1)[0][0]
            label = f"Spam: {SPAM_CATEGORIES[top]} ({len(spam)})"
        blocked = len(spam) - safe >= block_threshold

    label = label[:200] if label else None
    if (label, blocked) != (phone.label, phone.blocked):
        phone.label = label
        phone.blocked = blocked
        phone.version = _next_version(session)


def _next_version(session: Session) -> int:
    return session.execute(
        update(SyncState).where(SyncState.id == 1).values(version=SyncState.version + 1).returning(SyncState.version)
    ).scalar_one()


def fold(text: str) -> str:
    """Lowercase and strip diacritics so "wroclaw" matches "Wrocław"."""
    text = text.lower().replace("ł", "l")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
