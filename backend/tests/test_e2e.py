"""Test end-to-end (T4.2): TED finto a livello HTTP → job → database migrato → API.

Il TED finto è un `httpx.MockTransport` collegato al vero `TedClient` (si esercitano anche
query, paginazione e ritentativi) e risponde con le fixture reali di `backend/tests/fixtures/`.
Il database è un SQLite su file creato con Alembic. Nessuna rete e nessuna attesa reale.

Scenari: giorno normale, doppia esecuzione, rettifica, TED non raggiungibile.
"""

import json
import re
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from backend.api import runs as runs_module
from backend.api.deps import get_now, get_pipeline_deps, get_session
from backend.api.main import create_app
from backend.domain.config import load_filters_config, load_scoring_config
from backend.domain.database import create_session_factory
from backend.ingestion import pipeline
from backend.ingestion.dedup import TedNoticeLookup
from backend.ingestion.pipeline import ROME, PipelineDeps
from backend.ingestion.ted_client import RETRY_DELAYS, TedClient, TedClientConfig

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "backend" / "tests" / "fixtures"
FIXTURE_FILES = (
    "ted_search_it_2026-10-14.json",
    "ted_search_it_changes_2026-10.json",
    "ted_lookup_change_predecessors.json",
)
DAY = date(2026, 10, 14)
ORIGINAL = "437009-2026"
ORIGINAL_DAY = date(2026, 6, 25)
CHANGE = "566426-2026"
CHANGE_DAY = date(2026, 8, 17)


def _rome(day: date, hour: int = 6) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=ROME)


def _load_all_notices() -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for name in FIXTURE_FILES:
        data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        for notice in data["response"]["notices"]:
            unique[notice["publication-number"]] = notice
    return list(unique.values())


ALL_NOTICES = _load_all_notices()


class FakeTed:
    """TED finto: risponde alle query del client con gli avvisi delle fixture."""

    def __init__(self) -> None:
        self.down = False
        self.queries: list[str] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        query = json.loads(request.content)["query"]
        self.queries.append(query)
        if self.down:
            return httpx.Response(503, text="Service Unavailable")
        if match := re.search(r"notice-identifier=([0-9a-f-]+)", query):
            found = [n for n in ALL_NOTICES if n["notice-identifier"] == match.group(1)]
        elif match := re.search(r"publication-date=(\d{4})(\d{2})(\d{2})", query):
            day = "-".join(match.groups())
            found = [n for n in ALL_NOTICES if n["publication-date"].startswith(day)]
        else:
            found = []
        body = {"notices": found, "totalNoticeCount": len(found), "iterationNextToken": None}
        return httpx.Response(200, json=body)

    def deps(self, factory: Callable[[], Session], now: Callable[[], datetime]) -> PipelineDeps:
        """Dipendenze del job con il vero TedClient su trasporto finto e attese finte."""
        client = TedClient(
            TedClientConfig(),
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            sleep=self.sleeps.append,
        )
        return PipelineDeps(
            session_factory=factory,  # type: ignore[arg-type]
            fetch_notices=client.fetch_notices,
            lookup=TedNoticeLookup(client.search),
            filters_config=load_filters_config(),
            scoring_config=load_scoring_config(),
            process_documents=lambda *args, **kwargs: [],
            now=now,
        )


class World:
    """Ambiente di prova: database migrato, TED finto, orologio mobile e API."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.factory = create_session_factory(engine)
        self.ted = FakeTed()
        self.now = _rome(DAY + timedelta(days=1))
        clock = lambda: self.now  # noqa: E731

        def session_override() -> Iterator[Session]:
            with self.factory() as session:
                yield session

        app = create_app()
        app.dependency_overrides[get_session] = session_override
        app.dependency_overrides[get_now] = lambda: self.now.astimezone(UTC)
        app.dependency_overrides[get_pipeline_deps] = lambda: self.ted.deps(self.factory, clock)
        self.client = TestClient(app)
        self.clock = clock

    def at(self, day: date, hour: int = 6) -> None:
        self.now = _rome(day, hour)

    def run_via_api(self) -> httpx.Response:
        """`POST /runs` e attesa della fine del job (thread in background)."""
        response = self.client.post("/runs")
        thread = runs_module._job_thread
        assert thread is not None
        thread.join(timeout=30)
        assert not thread.is_alive()
        return response

    def run_day(self, day: date) -> Any:
        """Esegue il job per un giorno preciso (stesse dipendenze di `POST /runs`)."""
        return pipeline.run_daily_ingestion(day, self.ted.deps(self.factory, self.clock))

    def tenders(self, **params: Any) -> dict:
        response = self.client.get("/tenders", params={"page_size": 100, **params})
        assert response.status_code == 200, response.text
        return response.json()

    def runs(self) -> list[dict]:
        return self.client.get("/runs", params={"limit": 100}).json()["items"]


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    url = f"sqlite:///{tmp_path / 'e2e.db'}"
    config = Config(str(ROOT / "backend" / "domain" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url, connect_args={"check_same_thread": False})
    yield World(engine)
    engine.dispose()


def _cn_numbers() -> set[str]:
    data = json.loads((FIXTURES / FIXTURE_FILES[0]).read_text(encoding="utf-8"))
    return {
        n["publication-number"]
        for n in data["response"]["notices"]
        if n["notice-type"] == "cn-standard"
    }


# --- Scenario 1: giorno normale ---


def test_normal_day_from_ted_to_api(world: World) -> None:
    response = world.run_via_api()
    assert response.status_code == 202 and response.json()["status"] == "running"

    # Il client ha interrogato TED per il solo giorno mancante (ieri), senza ritentativi.
    assert [q for q in world.ted.queries if "publication-date=" in q] == [
        q for q in world.ted.queries if "publication-date=20261014" in q
    ]
    assert any("publication-date=20261014" in q for q in world.ted.queries)
    assert world.ted.sleeps.count(RETRY_DELAYS[0]) == 0

    runs = world.runs()
    assert len(runs) == 1
    run = runs[0]
    assert run["id"] == response.json()["id"]
    assert (run["status"], run["run_date"]) == ("success", DAY.isoformat())
    assert (run["fetched_count"], run["new_count"], run["updated_count"]) == (9, 9, 0)

    listed = world.tenders()
    assert {t["publication_number"] for t in listed["items"]} == _cn_numbers()
    assert listed["total"] == len(_cn_numbers())
    scores = [t["relevance_score"] for t in listed["items"]]
    assert scores == sorted(scores, reverse=True)
    assert world.tenders(include_discarded=True)["total"] == 9

    first = listed["items"][0]
    detail = world.client.get(f"/tenders/{first['id']}")
    assert detail.status_code == 200 and detail.json() == first
    assert world.client.get(f"/tenders/{first['id']}/report").status_code == 404

    stats = world.client.get("/stats").json()
    assert stats["relevant_tenders"] == sum(t["is_relevant"] for t in listed["items"])
    assert stats["reports_to_verify"] == 0
    deadlines = world.client.get("/deadlines", params={"to": "2026-12-31"}).json()["items"]
    assert {d["tender_id"] for d in deadlines} <= {t["id"] for t in listed["items"]}


# --- Scenario 2: doppia esecuzione ---


def test_running_twice_does_not_duplicate_anything(world: World) -> None:
    first = world.run_via_api()
    before = world.tenders(include_discarded=True)
    second = world.run_via_api()
    after = world.tenders(include_discarded=True)

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] != second.json()["id"]
    assert before["total"] == after["total"] == 9
    assert [(t["id"], t["publication_number"], t["relevance_score"]) for t in before["items"]] == [
        (t["id"], t["publication_number"], t["relevance_score"]) for t in after["items"]
    ]

    runs = world.runs()
    assert [r["status"] for r in runs] == ["success", "success"]
    newest, oldest = runs
    assert (newest["new_count"], newest["updated_count"]) == (0, 9)
    assert (oldest["new_count"], oldest["updated_count"]) == (9, 0)
    assert newest["run_date"] == oldest["run_date"] == DAY.isoformat()


# --- Scenario 3: rettifica ---


def _verify_all_critical_fields(client: TestClient, tender_id: int) -> dict:
    body = {
        "summary": "Sintesi della gara originale.",
        "fields": [
            {
                "label": "Importo",
                "value": "100 EUR",
                "source_doc": "Disciplinare.pdf",
                "is_critical": True,
            },
            {
                "label": "Fatturato",
                "value": "1 Mln",
                "source_doc": "Disciplinare.pdf",
                "is_critical": True,
            },
            {"label": "Criterio", "value": "OEPV", "source_doc": "Bando.pdf", "is_critical": False},
        ],
    }
    created = client.post(f"/tenders/{tender_id}/report", json=body)
    assert created.status_code == 201
    report = created.json()
    for field in [f for f in report["fields"] if f["is_critical"]]:
        reviewed = client.patch(
            f"/reports/{report['id']}/fields/{field['id']}",
            json={"action": "confirm", "reviewer": "Giuseppe Rossi"},
        )
        assert reviewed.status_code == 200
        report = reviewed.json()
    return report


def _tender_by_number(world: World, number: str) -> dict:
    return next(
        t
        for t in world.tenders(include_discarded=True)["items"]
        if t["publication_number"] == number
    )


def test_change_notice_updates_tender_and_reopens_the_verified_report(world: World) -> None:
    world.at(ORIGINAL_DAY + timedelta(days=1))
    assert world.run_day(ORIGINAL_DAY).status.value == "success"
    original = _tender_by_number(world, ORIGINAL)
    old_deadline = datetime.fromisoformat(original["submission_deadline"])
    assert original["report_status"] == "none"

    verified = _verify_all_critical_fields(world.client, original["id"])
    assert verified["status"] == "verified"
    assert "revisionato da Giuseppe Rossi" in verified["ai_label"]
    assert _tender_by_number(world, ORIGINAL)["report_status"] == "verified"
    count_before = world.tenders(include_discarded=True)["total"]

    # Arriva la rettifica: stesso id della gara, scadenza nuova, report di nuovo da rivedere.
    world.at(CHANGE_DAY + timedelta(days=1))
    summary = world.run_day(CHANGE_DAY)
    assert summary.status.value == "success"

    after = _tender_by_number(world, ORIGINAL)
    assert after["id"] == original["id"]
    assert world.tenders(include_discarded=True)["total"] == count_before  # nessuna gara in più
    assert all(
        t["publication_number"] != CHANGE for t in world.tenders(include_discarded=True)["items"]
    )
    new_deadline = datetime.fromisoformat(after["submission_deadline"])
    assert new_deadline.astimezone(ROME).date() == date(2026, 10, 14)
    assert new_deadline > old_deadline

    assert after["report_status"] == "to_review"
    report = world.client.get(f"/tenders/{original['id']}/report").json()
    assert report["status"] == "to_review"
    assert {f["verification_status"] for f in report["fields"]} == {"verified", "to_verify"}
    assert world.client.get("/stats").json()["reports_to_verify"] == 1
    assert world.tenders(report_status="to_review", include_discarded=True)["total"] == 1

    # La rettifica si può rivedere: confermando di nuovo il report torna verificato.
    for field in [f for f in report["fields"] if f["is_critical"]][:1]:
        reconfirmed = world.client.patch(
            f"/reports/{report['id']}/fields/{field['id']}",
            json={"action": "confirm", "reviewer": "Anna Bianchi"},
        )
        assert reconfirmed.status_code == 200
    assert world.client.get(f"/tenders/{original['id']}/report").json()["status"] == "verified"


# --- Scenario 4: TED non raggiungibile ---


def test_ted_down_fails_the_run_without_touching_data_and_recovers_next_day(
    world: World,
) -> None:
    # Giorno 1 (15/10): normale, 9 avvisi salvati.
    assert world.run_via_api().status_code == 202
    saved = world.tenders(include_discarded=True)
    assert saved["total"] == 9

    # Giorno 2 (16/10): TED risponde 503 a tutti i tentativi.
    world.at(DAY + timedelta(days=2))
    world.ted.down = True
    world.ted.sleeps.clear()
    failed = world.run_via_api()
    assert failed.status_code == 202
    # Attese dei ritentativi (1 s, 2 s, 4 s) registrate dal finto `sleep`, senza aspettare davvero;
    # le altre attese sono la pausa minima tra due richieste.
    assert [d for d in world.ted.sleeps if d in RETRY_DELAYS] == list(RETRY_DELAYS)
    assert len([q for q in world.ted.queries if "publication-date=20261015" in q]) == 4

    newest = world.runs()[0]
    assert newest["id"] == failed.json()["id"]
    assert (newest["status"], newest["run_date"]) == ("failed", date(2026, 10, 15).isoformat())
    assert "TED non raggiungibile" in newest["error_message"]
    assert "503" in newest["error_message"]
    assert (newest["fetched_count"], newest["new_count"], newest["updated_count"]) == (0, 0, 0)
    assert newest["finished_at"] is not None
    assert world.tenders(include_discarded=True) == saved  # nessuna gara toccata

    # Giorno 3 (17/10): TED torna; il recupero elabora anche il 15 (fallito) e il 16.
    world.at(DAY + timedelta(days=3))
    world.ted.down = False
    recovered = world.run_via_api()
    assert recovered.status_code == 202
    runs = world.runs()
    successes = [r for r in runs if r["status"] == "success"]
    assert {r["run_date"] for r in successes} == {
        DAY.isoformat(),
        "2026-10-15",
        "2026-10-16",
    }
    assert [r["status"] for r in runs].count("failed") == 1  # il fallimento resta nello storico
    assert world.tenders(include_discarded=True)["total"] == 9
