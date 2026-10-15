"""Dipendenze condivise dei router: sessione del database."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from backend.domain.database import create_db_engine, create_session_factory


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    """Factory di sessioni creata alla prima richiesta, con `DATABASE_URL` dall'ambiente."""
    return create_session_factory(create_db_engine())


def get_session() -> Iterator[Session]:
    """Una sessione per richiesta, chiusa al termine. Nei test si sostituisce con un override."""
    with _session_factory()() as session:
        yield session
