"""Fixture condivise dai test del modulo domain: database SQLite in memoria, senza rete."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, StaticPool, create_engine
from sqlalchemy.orm import Session

from backend.domain.database import create_session_factory
from backend.domain.models import Base
from backend.domain.schemas import TenderCreate
from backend.tests.domain.scoring_helpers import ConfigFactory, make_scoring_factory


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as s:
        yield s


def make_tender(**overrides: Any) -> TenderCreate:
    """Gara di prova valida; i campi si sovrascrivono con `overrides`."""
    data: dict[str, Any] = {
        "publication_number": "000001-2026",
        "title": "Sviluppo software gestionale",
        "buyer_name": "Comune di Prova",
        "buyer_city": "Roma",
        "cpv_codes": ["72000000"],
        "notice_type": "bando di gara",
        "publication_date": date(2026, 10, 1),
        "submission_deadline": datetime(2026, 11, 1, 12, 0, tzinfo=UTC),
        "ted_url": "https://example.invalid/000001-2026",
    }
    data.update(overrides)
    return TenderCreate(**data)


@pytest.fixture
def cfg(tmp_path: Path) -> ConfigFactory:
    """Crea una `ScoringConfig` di prova da un file temporaneo, con valori sovrascrivibili."""
    return make_scoring_factory(tmp_path)
