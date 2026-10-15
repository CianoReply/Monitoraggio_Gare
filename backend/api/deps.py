"""Dipendenze condivise dei router: sessione del database, orologio, dipendenze del job."""

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from backend.domain.database import create_db_engine, create_session_factory
from backend.ingestion.pipeline import PipelineDeps


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    """Factory di sessioni creata alla prima richiesta, con `DATABASE_URL` dall'ambiente."""
    return create_session_factory(create_db_engine())


def get_session() -> Iterator[Session]:
    """Una sessione per richiesta, chiusa al termine. Nei test si sostituisce con un override."""
    with _session_factory()() as session:
        yield session


def get_now() -> datetime:
    """Istante attuale (UTC). Nei test si sostituisce per avere date fisse."""
    return datetime.now(UTC)


def get_pipeline_deps() -> PipelineDeps | None:
    """Dipendenze del job di ingestion: `None` = quelle reali (database, TED). Override nei test."""
    return None
