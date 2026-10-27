from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from phone_blocker.config import Settings
from phone_blocker.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

# `phone_blocker.db.migrate` passes the URL directly; the alembic CLI uses DATABASE_URL.
url = config.attributes.get("database_url") or Settings.from_env().database_url

with create_engine(url).connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        # SQLite can't ALTER most things; batch mode rebuilds the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()
