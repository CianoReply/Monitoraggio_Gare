"""Database SQLite in memoria con i dati di `seed.py`, per i test dell'API."""

from collections.abc import Iterator
from datetime import date

from fastapi import FastAPI
from sqlalchemy import Engine, StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.api.deps import get_session
from backend.api.main import create_app
from backend.domain.database import create_session_factory
from backend.domain.models import Base
from backend.domain.seed import seed

SEED_TODAY = date(2026, 10, 15)


def make_seeded_engine() -> Engine:
    """Crea le tabelle in un SQLite in memoria e vi inserisce i dati fittizi di `seed.py`."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as session:
        seed(session, today=SEED_TODAY)
        session.commit()
    return engine


def make_app(engine: Engine) -> FastAPI:
    """Applicazione che legge dal database indicato invece che da `DATABASE_URL`."""
    app = create_app()
    factory: sessionmaker[Session] = create_session_factory(engine)

    def override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    return app
