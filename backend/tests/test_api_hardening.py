"""Test di robustezza e sicurezza dell'API (fix/api-hardening): valori estremi, corpi stretti,
avvio concorrente, ciclo di vita, host ammessi, CORS, documentazione, messaggi in italiano."""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.api import main as main_module
from backend.api import runs as runs_module
from backend.api import schemas
from backend.api.main import (
    RESTART_ERROR_MESSAGE,
    close_interrupted_runs,
    create_app,
)
from backend.domain.database import create_session_factory
from backend.domain.models import IngestionRun, Report, RunStatus, Tender
from backend.tests.api_db import FIXED_NOW, SEED_TODAY, make_app, make_seeded_engine

NUL = chr(0)


@pytest.fixture
def engine() -> Engine:
    return make_seeded_engine(file_backed=True)


@pytest.fixture
def client(engine: Engine) -> TestClient:
    return TestClient(make_app(engine))


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session


def _tender_without_report(db: Session) -> Tender:
    found = db.scalars(select(Tender).outerjoin(Report).where(Report.id.is_(None))).first()
    assert found is not None
    return found


def _error(response: Any, status: int = 422) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error", "message"}
    return body


# --- 1. Valori estremi: mai 500 ---


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/tenders/{}"),
        ("get", "/tenders/{}/documents"),
        ("get", "/tenders/{}/report"),
        ("post", "/tenders/{}/report"),
        ("patch", "/reports/{}/fields/1"),
        ("patch", "/reports/1/fields/{}"),
    ],
)
def test_ids_beyond_the_database_range_are_422(client: TestClient, method: str, path: str) -> None:
    body: dict[str, Any] = {"action": "confirm", "reviewer": "A"} if method == "patch" else {}
    if method == "post":
        body = {
            "summary": "x",
            "fields": [{"label": "a", "value": "b", "source_doc": "c.pdf", "is_critical": False}],
        }
    too_big = client.request(method, path.format(2_147_483_648), json=body)
    error = _error(too_big)
    assert error["error"] == "validation_error" and "2147483647" in error["message"]
    assert client.request(method, path.format(10**30), json=body).status_code == 422
    # Il massimo valido arriva fino alla ricerca e dà 404, non 500.
    assert client.request(method, path.format(2_147_483_647), json=body).status_code == 404


def test_page_beyond_one_million_is_422(client: TestClient) -> None:
    assert _error(client.get("/tenders", params={"page": 1_000_001}))["message"].startswith("page:")
    assert client.get("/tenders", params={"page": 10**30}).status_code == 422
    ok = client.get("/tenders", params={"page": 1_000_000})
    assert ok.status_code == 200 and ok.json()["items"] == []


@pytest.mark.parametrize("name", ["deadline_from", "deadline_to"])
@pytest.mark.parametrize("value", ["1899-12-31", "0001-01-01", "3000-01-01", "9999-12-31"])
def test_extreme_dates_in_tenders_are_422(client: TestClient, name: str, value: str) -> None:
    error = _error(client.get("/tenders", params={name: value}))
    assert error["message"].startswith(f"{name}:") and "1900" in error["message"]


@pytest.mark.parametrize("name", ["from", "to"])
@pytest.mark.parametrize("value", ["1899-12-31", "3000-01-01", "9999-12-31"])
def test_extreme_dates_in_deadlines_are_422(client: TestClient, name: str, value: str) -> None:
    _error(client.get("/deadlines", params={name: value}))


@pytest.mark.parametrize("value", ["1900-01-01", "2999-12-31"])
def test_boundary_years_are_accepted(client: TestClient, value: str) -> None:
    assert client.get("/tenders", params={"deadline_from": value}).status_code == 200
    assert client.get("/tenders", params={"deadline_to": value}).status_code == 200


def test_deadlines_range_wider_than_366_days_is_422(client: TestClient) -> None:
    start = SEED_TODAY
    ok = client.get(
        "/deadlines", params={"from": start.isoformat(), "to": (start + timedelta(366)).isoformat()}
    )
    assert ok.status_code == 200
    wide = client.get(
        "/deadlines", params={"from": start.isoformat(), "to": (start + timedelta(367)).isoformat()}
    )
    assert "366" in _error(wide)["message"]
    # Anche con `to` assente (= oggi + 30): un `from` molto nel passato supera il limite.
    assert client.get("/deadlines", params={"from": "2020-01-01"}).status_code == 422


@pytest.mark.parametrize("value", [10**17, 1e16 * 10, 1e300])
@pytest.mark.parametrize("name", ["min_value", "max_value"])
def test_amounts_beyond_the_column_are_422(client: TestClient, name: str, value: float) -> None:
    _error(client.get("/tenders", params={name: value}))


def test_amount_at_the_limit_is_accepted(client: TestClient) -> None:
    assert client.get("/tenders", params={"max_value": 1e16}).status_code == 200


def test_nul_in_text_filter_is_422(client: TestClient) -> None:
    error = _error(client.get("/tenders", params={"q": f"a{NUL}b"}))
    assert error["message"].startswith("q:") and "NUL" in error["message"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(summary=f"x{NUL}y"),
        lambda b: b["fields"][0].update(label=f"x{NUL}"),
        lambda b: b["fields"][0].update(value=f"{NUL}"),
        lambda b: b["fields"][0].update(source_doc=f"a{NUL}.pdf"),
    ],
)
def test_nul_in_report_body_is_422_and_nothing_is_saved(
    client: TestClient, db: Session, mutate: Any
) -> None:
    tender = _tender_without_report(db)
    body = {
        "summary": "Sintesi",
        "fields": [{"label": "A", "value": "B", "source_doc": "c.pdf", "is_critical": True}],
    }
    mutate(body)
    error = _error(client.post(f"/tenders/{tender.id}/report", json=body))
    assert error["error"] == "validation_error" and "NUL" in error["message"]
    assert client.get(f"/tenders/{tender.id}/report").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"action": "correct", "value": f"a{NUL}", "reviewer": "A"},
        {"action": "confirm", "reviewer": f"A{NUL}"},
    ],
)
def test_nul_in_review_body_is_422(client: TestClient, db: Session, body: dict) -> None:
    report = db.scalars(select(Report)).first()
    assert report is not None
    field = report.fields[0]
    before = client.get(f"/tenders/{report.tender_id}/report").json()
    error = _error(client.patch(f"/reports/{report.id}/fields/{field.id}", json=body))
    assert "NUL" in error["message"]
    assert client.get(f"/tenders/{report.tender_id}/report").json() == before


# --- 2. Corpi stretti (modelli del dominio) ---


def test_request_models_are_the_domain_ones() -> None:
    from backend.api import reports
    from backend.domain import reports as domain_reports

    assert reports.ReportCreate is domain_reports.ReportCreate
    assert reports.FieldReview is domain_reports.FieldReview
    for name in ("ReportCreate", "FieldReview", "ReportFieldCreate"):
        assert not hasattr(schemas, name)


@pytest.mark.parametrize(
    "field_patch",
    [
        {"source_page": "2"},
        {"source_page": 1.5},
        {"source_page": True},
        {"is_critical": 1},
        {"is_critical": "true"},
        {"label": 5},
    ],
)
def test_strict_types_reject_coercions(client: TestClient, db: Session, field_patch: dict) -> None:
    tender = _tender_without_report(db)
    field = {"label": "A", "value": "B", "source_doc": "c.pdf", "is_critical": True, **field_patch}
    response = client.post(f"/tenders/{tender.id}/report", json={"summary": "S", "fields": [field]})
    assert _error(response)["error"] == "validation_error"


def test_naive_generated_at_is_rejected(client: TestClient, db: Session) -> None:
    tender = _tender_without_report(db)
    body = {
        "summary": "S",
        "generated_at": "2026-10-14T09:15:00",
        "fields": [{"label": "A", "value": "B", "source_doc": "c.pdf", "is_critical": True}],
    }
    _error(client.post(f"/tenders/{tender.id}/report", json=body))


# --- 3. POST /runs: richieste davvero concorrenti ---


def test_two_truly_concurrent_post_runs_one_wins_and_the_other_gets_409(engine: Engine) -> None:
    app = make_app(engine)
    inside = threading.Event()
    release = threading.Event()
    real_latest = runs_module._latest_run_id

    def slow_latest(session: Session) -> int:
        inside.set()  # la prima richiesta ha il lock e si ferma qui
        assert release.wait(timeout=10)
        return real_latest(session)

    results: dict[str, Any] = {}

    def first() -> None:
        results["first"] = TestClient(app).post("/runs")

    original = runs_module._latest_run_id
    runs_module._latest_run_id = slow_latest  # type: ignore[assignment]
    thread = threading.Thread(target=first)
    try:
        thread.start()
        assert inside.wait(timeout=10)
        second = TestClient(app).post("/runs")  # il lock è occupato: 409 subito, senza attendere
        body = _error(second, 409)
        assert body["error"] == "run_in_progress"
    finally:
        release.set()
        thread.join(timeout=30)
        runs_module._latest_run_id = original  # type: ignore[assignment]
    assert results["first"].status_code == 202
    runs_module.wait_for_job(30)
    runs = TestClient(app).get("/runs").json()["items"]
    assert [r["id"] for r in runs].count(results["first"].json()["id"]) == 1


def test_wait_for_job_without_a_thread_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runs_module, "_job_thread", None)
    assert runs_module.wait_for_job(0.1) is True


# --- 4. Ciclo di vita ---


class FakeHooks:
    def __init__(self) -> None:
        self.started = 0


@pytest.fixture
def quiet_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "configure_logging", lambda *a, **k: None)
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)


def test_startup_closes_runs_left_running(engine: Engine, quiet_lifespan: None) -> None:
    factory = create_session_factory(engine)
    with factory() as session:
        for offset in (1, 2):
            session.add(
                IngestionRun(
                    run_date=SEED_TODAY - timedelta(days=offset),
                    started_at=FIXED_NOW - timedelta(hours=offset),
                    status=RunStatus.RUNNING,
                )
            )
        session.commit()
    with TestClient(make_app(engine)) as client:
        runs = client.get("/runs", params={"limit": 100}).json()["items"]
    assert not [r for r in runs if r["status"] == "running"]
    interrupted = [r for r in runs if r["error_message"] == RESTART_ERROR_MESSAGE]
    assert len(interrupted) == 2
    assert all(r["finished_at"] is not None for r in interrupted)


def test_close_interrupted_runs_returns_count_and_is_idempotent(engine: Engine) -> None:
    factory = create_session_factory(engine)
    with factory() as session:
        session.add(
            IngestionRun(run_date=SEED_TODAY, started_at=FIXED_NOW, status=RunStatus.RUNNING)
        )
        session.commit()
    assert close_interrupted_runs(factory) == 1
    assert close_interrupted_runs(factory) == 0


def test_startup_continues_when_the_database_is_not_available(quiet_lifespan: None) -> None:
    # Senza DATABASE_URL (rimossa dai test) la chiusura fallisce e viene registrata: l'app parte.
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200


def test_shutdown_waits_for_the_manual_job_with_a_short_timeout(
    engine: Engine, quiet_lifespan: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    job = threading.Thread(target=release.wait, args=(10,), daemon=True)
    job.start()
    monkeypatch.setattr(runs_module, "_job_thread", job)
    monkeypatch.setattr(main_module, "SHUTDOWN_WAIT_SECONDS", 0.3)
    started = datetime.now(UTC)
    try:
        with TestClient(make_app(engine)):
            pass
        waited = (datetime.now(UTC) - started).total_seconds()
        assert 0.25 <= waited < 5  # ha atteso il timeout, poi è uscito senza bloccarsi
        assert job.is_alive()
    finally:
        release.set()
        job.join(timeout=10)


def test_shutdown_returns_quickly_when_the_job_is_finished(
    engine: Engine, quiet_lifespan: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    done = threading.Thread(target=lambda: None)
    done.start()
    done.join()
    monkeypatch.setattr(runs_module, "_job_thread", done)
    started = datetime.now(UTC)
    with TestClient(make_app(engine)):
        pass
    assert (datetime.now(UTC) - started).total_seconds() < 5


# --- 5. Sicurezza ---


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:8000", "testserver"])
def test_default_hosts_are_allowed(host: str) -> None:
    assert TestClient(create_app()).get("/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "host", ["evil.example", "evil.example:8000", "localhost.evil.example", ""]
)
def test_unknown_host_is_rejected_in_json(host: str) -> None:
    response = TestClient(create_app()).get("/health", headers={"Host": host})
    assert _error(response, 400) == {"error": "invalid_host", "message": "Host non ammesso."}


def test_allowed_hosts_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", "radar.example, *.interno.example")
    client = TestClient(create_app())
    assert client.get("/health", headers={"Host": "radar.example"}).status_code == 200
    assert client.get("/health", headers={"Host": "api.interno.example:8000"}).status_code == 200
    assert client.get("/health", headers={"Host": "localhost"}).status_code == 400


def test_wildcard_host_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    response = TestClient(create_app()).get("/health", headers={"Host": "qualsiasi.example"})
    assert response.status_code == 200


def test_host_check_runs_before_the_rest(engine: Engine) -> None:
    response = TestClient(make_app(engine)).get("/tenders", headers={"Host": "evil.example"})
    assert response.status_code == 400


@pytest.mark.parametrize("value", ["*", "http://localhost:3000, *", " * "])
def test_wildcard_cors_origin_is_refused_at_startup(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", value)
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        create_app()


def test_cors_allowed_headers_are_explicit() -> None:
    client = TestClient(create_app())
    ok = client.options(
        "/tenders",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert ok.status_code == 200
    assert "*" not in ok.headers["access-control-allow-headers"]
    refused = client.options(
        "/tenders",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-custom-secret",
        },
    )
    assert refused.status_code == 400


def test_docs_are_enabled_by_default() -> None:
    client = TestClient(create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 200, path


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off"])
def test_docs_can_be_turned_off(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("DOCS_ENABLED", value)
    client = TestClient(create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        response = client.get(path)
        assert _error(response, 404)["error"] == "not_found", path
    assert client.get("/health").status_code == 200  # il resto funziona


@pytest.mark.parametrize("value", ["", "true", "1"])
def test_docs_stay_on_for_other_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("DOCS_ENABLED", value)
    assert TestClient(create_app()).get("/openapi.json").status_code == 200


def test_dockerignore_excludes_tests() -> None:
    from pathlib import Path

    lines = (Path(__file__).resolve().parents[2] / ".dockerignore").read_text().splitlines()
    assert "backend/tests" in lines


# --- 6. Messaggi in italiano ---


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("/tenders?page=abc", "page: deve essere un numero intero"),
        ("/tenders?page=0", "page: deve essere maggiore o uguale a 1"),
        ("/tenders?page_size=101", "page_size: deve essere minore o uguale a 100"),
        ("/tenders?min_score=9", "min_score: deve essere minore o uguale a 5"),
        ("/tenders?cpv=abc", "cpv: formato non valido"),
        ("/tenders?sort=boh", "sort: valore non ammesso (valori ammessi: "),
        ("/tenders?deadline_from=ieri", "deadline_from: data non valida (formato AAAA-MM-GG)"),
        ("/tenders?min_value=x", "min_value: deve essere un numero"),
        ("/tenders?include_discarded=forse", "include_discarded: deve essere true o false"),
        ("/tenders?q=", "q: troppo corto (minimo 1 caratteri)"),
        ("/tenders/abc", "id: deve essere un numero intero"),
        ("/runs?limit=0", "limit: deve essere maggiore o uguale a 1"),
    ],
)
def test_validation_messages_are_in_italian(client: TestClient, url: str, expected: str) -> None:
    message = _error(client.get(url))["message"]
    assert message.startswith(expected), message
    for english in ("Input should", "Field required", "valid integer", "greater than"):
        assert english not in message


def test_body_validation_messages_are_in_italian(client: TestClient, db: Session) -> None:
    tender = _tender_without_report(db)
    response = client.post(f"/tenders/{tender.id}/report", json={"fields": []})
    message = _error(response)["message"]
    assert "summary: campo obbligatorio" in message
    assert "fields: deve contenere almeno 1 elementi" in message
    invalid = client.post(
        f"/tenders/{tender.id}/report", content="{", headers={"Content-Type": "application/json"}
    )
    assert "JSON non valido" in _error(invalid)["message"]


def test_404_and_405_messages_are_in_italian(client: TestClient) -> None:
    assert _error(client.get("/non-esiste"), 404) == {
        "error": "not_found",
        "message": "Risorsa non trovata.",
    }
    assert _error(client.delete("/tenders/1"), 405) == {
        "error": "method_not_allowed",
        "message": "Metodo non consentito per questa risorsa.",
    }


def test_stats_has_no_assert_statements() -> None:
    from pathlib import Path

    source = (Path(main_module.__file__).parent / "stats.py").read_text(encoding="utf-8")
    assert "assert " not in source
