"""Test di GET /runs e POST /runs (T3.5). TED è sostituito: nessuna rete."""

import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS31Validator, oas31_format_checker
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.api import runs as runs_module
from backend.domain.database import create_session_factory
from backend.domain.models import IngestionRun, RunStatus
from backend.domain.repository import InvalidQueryError
from backend.ingestion import pipeline
from backend.tests.api_db import (
    FIXED_NOW,
    SEED_TODAY,
    fake_pipeline_deps,
    make_app,
    make_seeded_engine,
)
from backend.tests.contract_utils import resolve

YESTERDAY = SEED_TODAY - timedelta(days=1)


@pytest.fixture
def engine() -> Engine:
    # File temporaneo: il job gira in un thread e non può condividere la connessione dell'API.
    return make_seeded_engine(file_backed=True)


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session


def _wait_job() -> None:
    thread = runs_module._job_thread
    assert thread is not None
    thread.join(timeout=10)
    assert not thread.is_alive()


def _runs(client: TestClient, **params: Any) -> list[dict]:
    response = client.get("/runs", params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


# --- GET /runs --------------------------------------------------------------------------------


@pytest.mark.contract
def test_get_runs_conforms_to_contract(engine: Engine, spec: dict) -> None:
    response = TestClient(make_app(engine)).get("/runs")
    assert response.status_code == 200
    media = spec["paths"]["/runs"]["get"]["responses"]["200"]
    schema = resolve(spec, media)["content"]["application/json"]["schema"]
    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
    assert [e.message for e in validator.iter_errors(response.json())] == []


def test_get_runs_matches_database_most_recent_first(engine: Engine, db: Session) -> None:
    items = _runs(TestClient(make_app(engine)))
    expected = db.scalars(
        select(IngestionRun).order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
    ).all()
    assert [i["id"] for i in items] == [r.id for r in expected]
    assert [(i["status"], i["run_date"]) for i in items] == [
        (r.status.value, r.run_date.isoformat()) for r in expected
    ]
    failed = next(i for i in items if i["status"] == "failed")
    assert failed["error_message"]
    for item in items:
        assert datetime.fromisoformat(item["started_at"]).utcoffset() is not None


def test_get_runs_limit(engine: Engine) -> None:
    client = TestClient(make_app(engine))
    assert len(_runs(client, limit=1)) == 1
    assert len(_runs(client, limit=100)) == 2


@pytest.mark.parametrize("limit", ["0", "101", "abc", "-1"])
def test_get_runs_invalid_limit_is_422(engine: Engine, limit: str) -> None:
    response = TestClient(make_app(engine)).get("/runs", params={"limit": limit})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


# --- POST /runs: avvio -------------------------------------------------------------------------


def test_post_runs_returns_202_with_new_run_id_and_runs_the_job(engine: Engine) -> None:
    fetched: list[date] = []

    def fetch(day: date) -> list[dict[str, Any]]:
        fetched.append(day)
        return []

    client = TestClient(make_app(engine, fake_pipeline_deps(engine, fetch)))
    before = {r["id"] for r in _runs(client)}
    response = client.post("/runs")
    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"id", "status"}
    assert body["status"] == "running"
    assert body["id"] not in before
    _wait_job()

    # Il giorno mancante (14/10: l'ultimo riuscito è il 13) è stato elaborato e registrato.
    assert fetched == [YESTERDAY]
    created = next(r for r in _runs(client) if r["id"] == body["id"])
    assert created["status"] == "success"
    assert created["run_date"] == YESTERDAY.isoformat()
    assert created["finished_at"] is not None


def test_post_runs_without_pending_days_reprocesses_yesterday(engine: Engine, db: Session) -> None:
    db.add(
        IngestionRun(
            run_date=YESTERDAY,
            started_at=FIXED_NOW - timedelta(hours=1),
            finished_at=FIXED_NOW - timedelta(minutes=50),
            status=RunStatus.SUCCESS,
        )
    )
    db.commit()
    fetched: list[date] = []
    client = TestClient(
        make_app(engine, fake_pipeline_deps(engine, lambda d: fetched.append(d) or []))
    )
    response = client.post("/runs")
    assert response.status_code == 202
    _wait_job()
    assert fetched == [YESTERDAY]
    assert next(r for r in _runs(client) if r["id"] == response.json()["id"])["status"] == "success"


def test_post_runs_with_failing_fetch_still_returns_202_and_records_failure(
    engine: Engine,
) -> None:
    def fetch(day: date) -> list[dict[str, Any]]:
        raise ConnectionError("TED non raggiungibile")

    client = TestClient(make_app(engine, fake_pipeline_deps(engine, fetch)))
    response = client.post("/runs")
    assert response.status_code == 202
    _wait_job()
    run = next(r for r in _runs(client) if r["id"] == response.json()["id"])
    assert run["status"] == "failed"
    assert "TED non raggiungibile" in run["error_message"]


# --- POST /runs: 409 ---------------------------------------------------------------------------


def test_second_post_while_running_returns_409_then_allows_a_new_run(engine: Engine) -> None:
    started, release = threading.Event(), threading.Event()

    def blocking_fetch(day: date) -> list[dict[str, Any]]:
        started.set()
        assert release.wait(timeout=10)
        return []

    client = TestClient(make_app(engine, fake_pipeline_deps(engine, blocking_fetch)))
    first = client.post("/runs")
    assert first.status_code == 202
    assert started.wait(timeout=10)
    try:
        second = client.post("/runs")
        assert second.status_code == 409
        assert second.json() == {
            "error": "run_in_progress",
            "message": f"L'esecuzione {first.json()['id']} è già in corso.",
        }
        # Il rifiuto non crea nuove esecuzioni.
        assert [r["status"] for r in _runs(client)].count("running") == 1
    finally:
        release.set()
        _wait_job()
    third = client.post("/runs")
    assert third.status_code == 202
    assert third.json()["id"] != first.json()["id"]


def test_post_returns_409_when_a_recent_running_row_exists(engine: Engine, db: Session) -> None:
    running = IngestionRun(
        run_date=YESTERDAY, started_at=FIXED_NOW - timedelta(minutes=5), status=RunStatus.RUNNING
    )
    db.add(running)
    db.commit()
    response = TestClient(make_app(engine)).post("/runs")
    assert response.status_code == 409
    assert response.json() == {
        "error": "run_in_progress",
        "message": f"L'esecuzione {running.id} è già in corso.",
    }


def test_stale_running_row_does_not_block_a_new_run(engine: Engine, db: Session) -> None:
    stale = IngestionRun(
        run_date=YESTERDAY - timedelta(days=1),
        started_at=FIXED_NOW - pipeline.STALE_RUN_AFTER - timedelta(hours=1),
        status=RunStatus.RUNNING,
    )
    db.add(stale)
    db.commit()
    client = TestClient(make_app(engine))
    assert client.post("/runs").status_code == 202
    _wait_job()
    states = {r["id"]: r["status"] for r in _runs(client)}
    assert states[stale.id] == "failed"  # chiusa dal job


def test_post_returns_409_when_the_job_lock_is_held_elsewhere(engine: Engine) -> None:
    client = TestClient(make_app(engine))
    with pipeline.exclusive_run():
        response = client.post("/runs")
    assert response.status_code == 409
    assert response.json()["error"] == "run_in_progress"


def test_post_while_previous_thread_is_alive_returns_409(engine: Engine) -> None:
    release = threading.Event()
    thread = threading.Thread(target=release.wait, args=(10,), daemon=True)
    thread.start()
    previous = runs_module._job_thread
    runs_module._job_thread = thread
    try:
        response = TestClient(make_app(engine)).post("/runs")
        assert response.status_code == 409
        assert response.json() == {
            "error": "run_in_progress",
            "message": "Un'esecuzione è già in corso.",
        }
    finally:
        release.set()
        thread.join(timeout=10)
        runs_module._job_thread = previous


def test_unexpected_job_failure_returns_500_without_details(engine: Engine) -> None:
    deps = fake_pipeline_deps(engine)

    def broken_factory() -> Session:
        raise RuntimeError("segreto interno")

    deps.session_factory = broken_factory  # type: ignore[assignment]
    client = TestClient(make_app(engine, deps), raise_server_exceptions=False)
    response = client.post("/runs")
    assert response.status_code == 500
    assert response.json() == {"error": "internal_error", "message": "Errore interno del server."}


def test_manual_run_dependencies_default_to_real_ones() -> None:
    from backend.api.deps import get_pipeline_deps

    assert get_pipeline_deps() is None


def test_get_runs_default_limit_is_20(engine: Engine, db: Session) -> None:
    for offset in range(25):
        db.add(
            IngestionRun(
                run_date=date(2026, 1, 1) + timedelta(days=offset),
                started_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=offset),
                finished_at=datetime(2026, 1, 1, 1, tzinfo=UTC) + timedelta(days=offset),
                status=RunStatus.SUCCESS,
            )
        )
    db.commit()
    assert len(_runs(TestClient(make_app(engine)))) == 20


# --- POST /runs: casi limite del thread ---


def _insert_run_and_finish(engine: Engine):  # type: ignore[no-untyped-def]
    """Finto job: crea subito la riga e termina, come una pipeline velocissima."""

    def job(deps: object, failure: list[BaseException]) -> None:
        with create_session_factory(engine)() as session:
            session.add(
                IngestionRun(
                    run_date=YESTERDAY,
                    started_at=FIXED_NOW,
                    finished_at=FIXED_NOW,
                    status=RunStatus.SUCCESS,
                )
            )
            session.commit()

    return job


def test_job_that_creates_the_row_and_ends_between_poll_and_liveness_check_gives_202(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_module, "_job", _insert_run_and_finish(engine))
    real_list_runs = runs_module.repository.list_runs
    calls = {"count": 0}

    def list_runs_with_race(session: Session, limit: int = 20) -> list[IngestionRun]:
        result = real_list_runs(session, limit)
        calls["count"] += 1
        if calls["count"] == 2:  # prima lettura del ciclo: poi il job crea la riga e termina
            thread = runs_module._job_thread
            assert thread is not None
            thread.join(timeout=10)
        return result

    monkeypatch.setattr(runs_module.repository, "list_runs", list_runs_with_race)
    response = TestClient(make_app(engine)).post("/runs")
    assert response.status_code == 202
    assert response.json()["status"] == "running"
    assert calls["count"] >= 3  # la riga è stata trovata alla rilettura


def test_job_that_ends_immediately_after_creating_the_row_gives_202(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_module, "_job", _insert_run_and_finish(engine))
    response = TestClient(make_app(engine)).post("/runs")
    assert response.status_code == 202
    ids = [r["id"] for r in _runs(TestClient(make_app(engine)))]
    assert response.json()["id"] in ids


def test_job_that_never_creates_a_row_gives_500(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runs_module, "_job", lambda deps, failure: None)
    client = TestClient(make_app(engine), raise_server_exceptions=False)
    response = client.post("/runs")
    assert response.status_code == 500
    assert response.json()["error"] == "internal_error"


def test_job_without_session_factory_reuses_the_cached_one(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = create_session_factory(engine)
    used = {"count": 0}

    def cached_factory():  # type: ignore[no-untyped-def]
        used["count"] += 1
        return factory

    def no_new_engine() -> None:
        raise AssertionError("non va creato un engine nuovo")

    monkeypatch.setattr(runs_module, "session_factory", cached_factory)
    monkeypatch.setattr(pipeline, "create_db_engine", no_new_engine)
    deps = fake_pipeline_deps(engine)
    deps.session_factory = None  # come con le dipendenze reali: la factory arriva dalla cache
    failure: list[BaseException] = []
    runs_module._job(deps, failure)
    assert failure == []
    assert used["count"] == 1
    with factory() as session:
        assert session.scalar(select(IngestionRun).where(IngestionRun.run_date == YESTERDAY))


def test_runs_invalid_query_error_is_422_but_other_value_error_is_500(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid(*args: Any, **kwargs: Any) -> None:
        raise InvalidQueryError("limit non valido dal repository")

    def other(*args: Any, **kwargs: Any) -> None:
        raise ValueError("errore interno qualsiasi")

    client = TestClient(make_app(engine), raise_server_exceptions=False)
    monkeypatch.setattr(runs_module.repository, "list_runs", invalid)
    response = client.get("/runs")
    assert response.status_code == 422
    assert response.json() == {
        "error": "validation_error",
        "message": "limit non valido dal repository",
    }
    monkeypatch.setattr(runs_module.repository, "list_runs", other)
    assert client.get("/runs").status_code == 500
