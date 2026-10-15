"""Database SQLite in memoria con i dati di `seed.py`, per i test dell'API."""

import tempfile
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy import Engine, StaticPool, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.api.deps import get_now, get_pipeline_deps, get_session
from backend.api.main import create_app
from backend.domain.database import create_session_factory
from backend.domain.models import Base
from backend.domain.seed import seed
from backend.ingestion.pipeline import PipelineDeps

SEED_TODAY = date(2026, 10, 15)
# Orologio fisso dei test: il giorno del seed a mezzogiorno UTC (14:00 a Roma, ora legale).
FIXED_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


_TEMP_DIRS: list[tempfile.TemporaryDirectory[str]] = []


def make_seeded_engine(*, file_backed: bool = False) -> Engine:
    """Crea le tabelle in un SQLite e vi inserisce i dati fittizi di `seed.py`.

    In memoria (predefinito) tutte le sessioni condividono una sola connessione: va bene per i
    test sincroni. Se il test avvia thread che scrivono (`POST /runs`) serve `file_backed=True`:
    un file temporaneo con connessioni separate, come in produzione.
    """
    if file_backed:
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        _TEMP_DIRS.append(folder)
        engine = create_engine(
            f"sqlite:///{Path(folder.name) / 'test.db'}", connect_args={"check_same_thread": False}
        )
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as session:
        seed(session, today=SEED_TODAY)
        session.commit()
    return engine


def fake_pipeline_deps(
    engine: Engine,
    fetch_notices: Callable[[date], list[dict[str, Any]]] | None = None,
) -> PipelineDeps:
    """Dipendenze del job di ingestion senza rete: TED sostituito, database in memoria."""
    return PipelineDeps(
        session_factory=create_session_factory(engine),
        fetch_notices=fetch_notices or (lambda day: []),
        lookup=lambda identifier: None,
        now=lambda: FIXED_NOW,
    )


def make_app(
    engine: Engine,
    pipeline_deps: PipelineDeps | None = None,
    now: datetime = FIXED_NOW,
) -> FastAPI:
    """Applicazione che legge dal database indicato invece che da `DATABASE_URL`.

    `now` è l'orologio dell'API; `pipeline_deps` sostituisce TED e il resto del job di ingestion
    (predefinito: nessuna notizia da TED, mai la rete).
    """
    factory: sessionmaker[Session] = create_session_factory(engine)
    app = create_app(factory)
    pipeline_deps = pipeline_deps or fake_pipeline_deps(engine)

    def override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_now] = lambda: now
    app.dependency_overrides[get_pipeline_deps] = lambda: pipeline_deps
    return app
