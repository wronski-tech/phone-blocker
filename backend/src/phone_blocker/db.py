from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base, SyncState


def make_sessionmaker(database_url: str) -> sessionmaker[Session]:
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if database_url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, **kwargs)
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        if session.get(SyncState, 1) is None:
            session.add(SyncState(id=1, version=0))
    return sessionmaker(engine, expire_on_commit=False)
