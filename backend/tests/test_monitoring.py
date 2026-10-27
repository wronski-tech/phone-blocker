import os
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from phone_blocker.api import create_app
from phone_blocker.config import Settings
from phone_blocker.db import make_sessionmaker
from phone_blocker.importer import DEFAULT_SOURCES
from phone_blocker.models import ImportRun, utcnow


@pytest.fixture
def backups(tmp_path):
    path = tmp_path / "backups"
    path.mkdir()
    return path


@pytest.fixture
def client(db_url, backups):
    with TestClient(create_app(Settings(database_url=db_url, backup_dir=str(backups)))) as c:
        yield c


def finished_runs(db_url, age: timedelta, status="success"):
    with make_sessionmaker(db_url).begin() as session:
        for source in DEFAULT_SOURCES:
            session.add(ImportRun(source=source, status=status, started_at=utcnow() - age,
                                  finished_at=utcnow() - age, saved=1, removed=0, errors=0))


def dump(backups, age: timedelta):
    path = backups / f"phone_blocker-{time.time_ns()}.dump"
    path.write_bytes(b"x")
    mtime = time.time() - age.total_seconds()
    os.utime(path, (mtime, mtime))


def test_fresh_install_is_alive_but_not_healthy(client):
    assert client.get("/health").status_code == 200
    response = client.get("/status")
    assert response.status_code == 503
    checks = response.json()["checks"]
    assert checks["database"]["ok"] is True
    assert checks["import:bip"] == {"ok": False, "last_success": None}
    assert checks["backup"] == {"ok": False, "newest": None, "file": None}


def test_healthy_with_recent_imports_and_backup_then_stale(client, db_url, backups):
    finished_runs(db_url, timedelta(days=2))
    finished_runs(db_url, timedelta(hours=1), status="failed")  # a later failure alone is not staleness
    dump(backups, timedelta(days=3))
    dump(backups, timedelta(hours=20))
    assert client.get("/status").status_code == 200

    for old in backups.iterdir():
        os.utime(old, (time.time() - 3 * 86400,) * 2)
    response = client.get("/status")
    assert response.status_code == 503
    assert response.json()["checks"]["backup"]["ok"] is False
    assert response.json()["checks"]["import:nfz"]["ok"] is True


def test_imports_older_than_three_days_are_stale(client, db_url, backups):
    finished_runs(db_url, timedelta(days=4))
    dump(backups, timedelta(hours=1))
    checks = client.get("/status").json()["checks"]
    assert [checks[f"import:{s}"]["ok"] for s in DEFAULT_SOURCES] == [False] * len(DEFAULT_SOURCES)
