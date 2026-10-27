from types import SimpleNamespace

import pytest
from sqlalchemy import select

from phone_blocker import importer
from phone_blocker.db import make_sessionmaker
from phone_blocker.directory import ListedPhone, OrganizationRecord
from phone_blocker.models import Organization, PhoneNumber


@pytest.fixture
def sessions(db_url):
    return make_sessionmaker(db_url)


def record(n: int) -> OrganizationRecord:
    return OrganizationRecord(f"org-{n}", f"Org {n}", phones=[ListedPhone(48713000000 + n, "phone")])


def run(sessions, monkeypatch, items, **kwargs):
    """Run the importer with a fake source that yields `items` (or raises an exception item)."""
    def iter_records(ctx, client):
        for item in items:
            if isinstance(item, Exception):
                raise item
            yield item

    monkeypatch.setitem(importer.SOURCES, "fake", SimpleNamespace(DEFAULT_DELAY=0, iter_records=iter_records))
    return importer.run_import(sessions, "fake", block_threshold=1, log=lambda _: None, **kwargs)


def org_ids(sessions):
    with sessions() as session:
        return sorted(session.scalars(select(Organization.source_id)))


def label(sessions, n):
    with sessions() as session:
        return session.scalar(select(PhoneNumber.label).where(PhoneNumber.number == 48713000000 + n))


def test_complete_run_removes_entries_the_source_no_longer_lists(sessions, monkeypatch):
    first = run(sessions, monkeypatch, [(f"org-{n}", record(n)) for n in (1, 2, 3)])
    assert (first.status, first.saved, first.removed) == ("success", 3, 0)

    # org-2 is listed but unchanged (record None, e.g. refreshed recently); org-3 is gone.
    second = run(sessions, monkeypatch, [("org-1", record(1)), ("org-2", None)])

    assert (second.status, second.saved, second.removed) == ("success", 1, 1)
    assert org_ids(sessions) == ["org-1", "org-2"]
    assert label(sessions, 2) == "Org 2"
    assert label(sessions, 3) is None  # the phone gets a removal in the next sync


def test_partial_and_failed_runs_remove_nothing(sessions, monkeypatch):
    run(sessions, monkeypatch, [(f"org-{n}", record(n)) for n in (1, 2, 3)])

    limited = run(sessions, monkeypatch, [("org-1", record(1)), ("org-4", record(4))], limit=1)
    failed = run(sessions, monkeypatch, [("org-1", record(1)), RuntimeError("API down")])

    assert (limited.status, limited.removed) == ("success", 0)
    assert (failed.status, failed.saved, failed.removed) == ("failed", 1, 0)
    assert failed.message == "RuntimeError: API down"
    assert org_ids(sessions) == ["org-1", "org-2", "org-3"]


def test_refuses_to_remove_a_large_share_of_entries(sessions, monkeypatch):
    run(sessions, monkeypatch, [(f"org-{n}", record(n)) for n in range(1, 21)])

    # 11 of 20 vanish: more than both 10 entries and 10%.
    result = run(sessions, monkeypatch, [(f"org-{n}", None) for n in range(1, 10)])

    assert (result.status, result.removed) == ("success", 0)
    assert result.message.startswith("Refused to remove 11 of 20")
    assert len(org_ids(sessions)) == 20
