"""Test di T1.6: log JSON e righe complete in `ingestion_runs`, senza rete."""

import io
import json
import logging
import sys
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.domain.config import load_filters_config, load_scoring_config
from backend.domain.database import create_session_factory
from backend.domain.models import Base, IngestionRun, RunStatus
from backend.ingestion.logging_config import JsonFormatter, configure_logging
from backend.ingestion.pipeline import ROME, PipelineDeps, run_daily_ingestion

DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=ROME)


@pytest.fixture
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


def deps(factory: sessionmaker[Session], fetch: Any) -> PipelineDeps:
    return PipelineDeps(
        session_factory=factory,
        fetch_notices=fetch,
        lookup=lambda identifier: None,
        filters_config=load_filters_config(),
        scoring_config=load_scoring_config(),
        process_documents=lambda *args, **kwargs: [],
        now=lambda: NOW,
    )


def only_run(factory: sessionmaker[Session]) -> IngestionRun:
    with factory() as session:
        [run] = session.scalars(select(IngestionRun)).all()
        return run


def record(message: str, **kwargs: Any) -> logging.LogRecord:
    return logging.LogRecord(
        "backend.ingestion.pipeline", logging.INFO, __file__, 1, message, (), None, **kwargs
    )


def test_json_formatter_has_level_time_module_message() -> None:
    line = JsonFormatter().format(record("Esecuzione %s avviata"))
    data = json.loads(line.replace("%s", "1"))
    assert set(data) == {"level", "time", "module", "message"}
    assert data["level"] == "INFO" and data["module"] == "backend.ingestion.pipeline"
    assert datetime.fromisoformat(data["time"]).utcoffset() is not None


def test_json_formatter_includes_exception_and_context() -> None:
    try:
        raise ValueError("dato non valido")
    except ValueError:
        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "errore", (), sys.exc_info())
    rec.context = {"run_id": 7, "level": "ignorato"}
    data = json.loads(JsonFormatter().format(rec))
    assert "ValueError: dato non valido" in data["exception"]
    assert data["run_id"] == 7 and data["level"] == "ERROR"


def test_configure_logging_writes_one_json_line_per_message() -> None:
    stream = io.StringIO()
    configure_logging(logging.INFO, stream)
    configure_logging(logging.INFO, stream)  # idempotente: un solo handler JSON
    logging.getLogger("backend.test").info("ciao %s", "mondo")
    lines = stream.getvalue().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["message"] == "ciao mondo"
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler.formatter, JsonFormatter):
            root.removeHandler(handler)


def test_successful_run_leaves_a_complete_row(factory: sessionmaker[Session]) -> None:
    run_daily_ingestion(DAY, deps(factory, lambda day: []))
    run = only_run(factory)
    assert run.status is RunStatus.SUCCESS and run.run_date == DAY
    assert run.started_at is not None and run.finished_at is not None
    assert run.finished_at >= run.started_at
    assert (run.fetched_count, run.new_count, run.updated_count, run.relevant_count) == (0, 0, 0, 0)
    assert run.error_message is None


def test_simulated_error_gives_failed_with_readable_message(
    factory: sessionmaker[Session],
) -> None:
    def broken(day: date) -> list[dict[str, Any]]:
        raise ConnectionError("TED non raggiungibile dopo 4 richieste: TED ha risposto 503")

    summary = run_daily_ingestion(DAY, deps(factory, broken))
    run = only_run(factory)
    assert run.status is RunStatus.FAILED and run.finished_at is not None
    assert run.error_message == (
        "ConnectionError: TED non raggiungibile dopo 4 richieste: TED ha risposto 503"
    )
    assert summary.error_message == run.error_message
