"""Test d'integrazione (T4.1): fixture TED → job → database migrato con Alembic → API.

Segue il flusso completo di un giorno senza rete: gli avvisi arrivano dalla fixture reale
del 2026-10-14, il database è un SQLite su file creato con `alembic upgrade head`.
"""

import json
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from backend.api.deps import get_session
from backend.api.main import create_app
from backend.domain.config import load_filters_config, load_scoring_config
from backend.domain.database import create_session_factory
from backend.ingestion.pipeline import ROME, PipelineDeps, run_daily_ingestion

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "ted_search_it_2026-10-14.json"
DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=ROME)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{tmp_path / 'integration.db'}"
    cfg = Config(str(ROOT / "backend" / "domain" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    factory = create_session_factory(engine)

    def override() -> Iterator[Session]:
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override
    return TestClient(app)


def notices() -> list[dict[str, Any]]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["response"]["notices"]


def run_day(engine: Engine) -> Any:
    deps = PipelineDeps(
        session_factory=create_session_factory(engine),
        fetch_notices=lambda day: notices() if day == DAY else [],
        lookup=lambda identifier: None,
        filters_config=load_filters_config(),
        scoring_config=load_scoring_config(),
        process_documents=lambda *args, **kwargs: [],
        now=lambda: NOW,
    )
    return run_daily_ingestion(DAY, deps)


def test_full_day_flow_makes_tenders_visible_in_the_api(engine: Engine, client: TestClient) -> None:
    summary = run_day(engine)
    assert summary.status.value == "success" and summary.new_count == 9

    listed = client.get("/tenders", params={"page_size": 100}).json()
    numbers = {item["publication_number"] for item in listed["items"]}
    # gli esiti (can-standard) sono scartati dai filtri e non compaiono di default (ADR-012)
    assert numbers == {
        n["publication-number"] for n in notices() if n["notice-type"] == "cn-standard"
    }
    assert listed["total"] == len(numbers)
    scores = [item["relevance_score"] for item in listed["items"]]
    assert scores == sorted(scores, reverse=True)

    everything = client.get("/tenders", params={"include_discarded": "true"}).json()
    assert everything["total"] == 9

    first = listed["items"][0]
    detail = client.get(f"/tenders/{first['id']}").json()
    assert detail["publication_number"] == first["publication_number"]
    assert detail["ted_url"].startswith("https://ted.europa.eu/")


def test_rerunning_the_day_keeps_the_api_stable(engine: Engine, client: TestClient) -> None:
    run_day(engine)
    before = client.get("/tenders", params={"include_discarded": "true"}).json()
    summary = run_day(engine)
    after = client.get("/tenders", params={"include_discarded": "true"}).json()
    assert summary.updated_count == 9 and summary.new_count == 0
    assert before["total"] == after["total"] == 9


def test_runs_are_visible_in_the_api(engine: Engine, client: TestClient) -> None:
    run_day(engine)
    runs = client.get("/runs").json()["items"]
    assert runs[0]["status"] == "success"
    assert runs[0]["fetched_count"] == 9 and runs[0]["new_count"] == 9
