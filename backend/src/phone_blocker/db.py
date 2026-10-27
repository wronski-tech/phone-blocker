from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_sessionmaker(database_url: str) -> sessionmaker[Session]:
    connect_args = {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite") else {}
    return sessionmaker(create_engine(database_url, connect_args=connect_args), expire_on_commit=False)


def migrate(database_url: str, revision: str = "head") -> None:
    """Apply Alembic migrations (shipped inside the package) up to `revision`."""
    config = Config()
    config.set_main_option("script_location", "phone_blocker:migrations")
    config.attributes["database_url"] = database_url
    command.upgrade(config, revision)
