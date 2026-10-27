from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from phone_blocker.models import Base


def test_migrations_match_models(db_url):
    """Fails when a model changes without a migration (run `alembic revision --autogenerate`)."""
    with create_engine(db_url).connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
