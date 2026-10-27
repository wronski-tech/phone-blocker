import os

import pytest
from sqlalchemy import MetaData, create_engine

from phone_blocker.db import migrate


@pytest.fixture
def db_url(tmp_path):
    """A freshly migrated database.

    SQLite by default; set TEST_DATABASE_URL to use PostgreSQL (wiped per test).
    """
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        engine = create_engine(url)
        existing = MetaData()
        existing.reflect(engine)
        existing.drop_all(engine)
        engine.dispose()
    else:
        url = f"sqlite:///{tmp_path / 'test.db'}"
    migrate(url)
    return url
