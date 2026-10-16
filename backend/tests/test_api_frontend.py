"""Test dell'API per il frontend (`/api`, ADR-016) sui dati di `seed.py`, senza rete.

Le attese si ricavano dal database con query indipendenti dall'API.
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.api import frontend
from backend.api.main import app as default_app
from backend.domain.database import create_session_factory
from backend.domain.models import IngestionRun, Report, RunStatus, Tender
from backend.domain.timeutil import ROME
from backend.tests.api_db import FIXED_NOW, make_app, make_seeded_engine

TENDER_KEYS = {
    "id",
    "publication_number",
    "title",
    "buyer_name",
    "cpv_codes",
    "estimated_value",
    "publication_date",
    "submission_deadline",
    "relevance_score",
    "report_status",
    "watch_status",
    "watched_at",
    "decision",
    "documents",
    "report",
}


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = make_seeded_engine()
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    return TestClient(make_app(engine))


def session_of(engine: Engine) -> Session:
    return create_session_factory(engine)()


def tender_with_report(engine: Engine) -> Tender:
    with session_of(engine) as s:
        report = s.scalars(select(Report).order_by(Report.id)).first()
        assert report is not None
        return s.get(Tender, report.tender_id)  # type: ignore[return-value]


def test_frontend_routes_are_not_in_the_public_contract() -> None:
    paths = default_app.openapi()["paths"]
    assert not any(p.startswith("/api") for p in paths)


def test_monitoring_status_reflects_last_run_and_schedule(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INGESTION_SCHEDULE", "06:00")
    body = client.get("/api/monitoring/status").json()
    with session_of(engine) as s:
        last = s.scalars(select(IngestionRun).order_by(IngestionRun.id.desc())).first()
    assert last is not None and last.status is RunStatus.FAILED
    assert body["state"] == "failed"
    moment = last.finished_at or last.started_at
    assert body["last_run_at"] == moment.astimezone(ROME).strftime("%Y-%m-%dT%H:%M")
    # FIXED_NOW = 15/10 12:00 UTC (14:00 a Roma): prossimo avvio il 16/10 alle 06:00
    assert body["next_run_at"] == "2026-10-16T06:00"


def test_monitoring_status_without_runs() -> None:
    eng = make_seeded_engine()
    with session_of(eng) as s:
        for run in s.scalars(select(IngestionRun)).all():
            s.delete(run)
        s.commit()
    body = TestClient(make_app(eng)).get("/api/monitoring/status").json()
    assert body["state"] == "ok" and body["last_run_at"] is None
    eng.dispose()


def test_next_run_at_today_or_tomorrow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGESTION_SCHEDULE", "06:00")
    early = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)  # 05:00 a Roma
    assert frontend.next_run_at(early) == datetime(2026, 10, 16, 6, 0, tzinfo=ROME)
    late = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)  # 07:00 a Roma
    assert frontend.next_run_at(late) == datetime(2026, 10, 17, 6, 0, tzinfo=ROME)


def test_published_today_is_the_last_processed_day(client: TestClient, engine: Engine) -> None:
    items = client.get("/api/tenders", params={"published": "today"}).json()
    with session_of(engine) as s:
        day = s.scalars(
            select(IngestionRun.run_date)
            .where(IngestionRun.status == RunStatus.SUCCESS)
            .order_by(IngestionRun.run_date.desc())
        ).first()
        expected = {
            t.publication_number
            for t in s.scalars(select(Tender).where(Tender.publication_date == day))
            if t.discard_reason is None
        }
    assert expected and {i["publication_number"] for i in items} == expected
    assert all(set(i) == TENDER_KEYS for i in items)
    scores = [i["relevance_score"] for i in items]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize(
    "params", [{}, {"published": "ieri"}, {"published": "today", "decided": "true"}]
)
def test_list_requires_exactly_one_valid_filter(client: TestClient, params: dict) -> None:
    response = client.get("/api/tenders", params=params)
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_tender_detail_format(client: TestClient, engine: Engine) -> None:
    tender = tender_with_report(engine)
    with session_of(engine) as s:
        report = s.scalars(select(Report).where(Report.tender_id == tender.id)).one()
        report_status = report.status.value
    body = client.get(f"/api/tenders/{tender.id}").json()
    assert set(body) == TENDER_KEYS
    assert body["id"] == str(tender.id)
    assert body["report_status"] == report_status
    assert body["watch_status"] == "none" and body["decision"] is None
    if tender.submission_deadline is not None:
        expected = tender.submission_deadline.astimezone(ROME).strftime("%Y-%m-%dT%H:%M")
        assert body["submission_deadline"] == expected
    fields = body["report"]["fields"]
    assert fields and all(f["verification_status"] in ("to_review", "verified") for f in fields)
    assert all(f["group"] in ("key_info", "requirements") for f in fields)


def test_tender_without_report_is_absent(client: TestClient, engine: Engine) -> None:
    with session_of(engine) as s:
        tender = next(t for t in s.scalars(select(Tender)) if t.report is None)
    body = client.get(f"/api/tenders/{tender.id}").json()
    assert body["report_status"] == "absent" and body["report"] is None


@pytest.mark.parametrize("tender_id", ["999999", "abc", "99999999999999999999", "-1"])
def test_unknown_tender_is_404(client: TestClient, tender_id: str) -> None:
    response = client.get(f"/api/tenders/{tender_id}")
    assert response.status_code == 404
    assert response.json()["error"] == "tender_not_found"


def test_documents_fall_back_to_the_notice_link(client: TestClient, engine: Engine) -> None:
    with session_of(engine) as s:
        tender = next(t for t in s.scalars(select(Tender)) if not t.documents and t.documents_url)
    docs = client.get(f"/api/tenders/{tender.id}").json()["documents"]
    assert docs == [
        {"name": "Documenti di gara", "status": "unavailable", "url": tender.documents_url}
    ]


def test_watch_flow(client: TestClient, engine: Engine) -> None:
    with session_of(engine) as s:
        tender = next(
            t
            for t in s.scalars(select(Tender))
            if t.submission_deadline is not None
            and t.submission_deadline > FIXED_NOW + timedelta(days=1)
        )
    put = client.put(f"/api/tenders/{tender.id}/watch", json={"watch_status": "watching"})
    assert put.status_code == 200
    assert put.json()["watch_status"] == "watching"
    assert put.json()["watched_at"] == FIXED_NOW.astimezone(ROME).date().isoformat()
    active = client.get("/api/tenders", params={"watch": "active"}).json()
    assert str(tender.id) in {i["id"] for i in active}

    client.put(f"/api/tenders/{tender.id}/watch", json={"watch_status": "none"})
    active = client.get("/api/tenders", params={"watch": "active"}).json()
    assert str(tender.id) not in {i["id"] for i in active}


@pytest.mark.parametrize("body", [{"watch_status": "boh"}, {}, {"watch_status": "none", "x": 1}])
def test_invalid_watch_is_422(client: TestClient, engine: Engine, body: dict) -> None:
    tender = tender_with_report(engine)
    assert client.put(f"/api/tenders/{tender.id}/watch", json=body).status_code == 422


def test_decision_flow_uses_the_user_header(client: TestClient, engine: Engine) -> None:
    tender = tender_with_report(engine)
    response = client.post(
        f"/api/tenders/{tender.id}/decision",
        json={"status": "candidate", "reason": "Ottima opportunità"},
        headers={"X-User-Name": "F. Ciano"},
    )
    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision == {
        "status": "candidate",
        "reason": "Ottima opportunità",
        "decided_at": FIXED_NOW.astimezone(ROME).date().isoformat(),
        "decided_by": "F. Ciano",
    }
    decided = client.get("/api/tenders", params={"decided": "true"}).json()
    assert [i["id"] for i in decided] == [str(tender.id)]


def test_decision_without_header_uses_default_user(
    client: TestClient, engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    tender = tender_with_report(engine)
    monkeypatch.setenv("FRONTEND_DEFAULT_USER", "Revisore di prova")
    body = client.post(f"/api/tenders/{tender.id}/decision", json={"status": "monitored"}).json()
    assert body["decision"]["decided_by"] == "Revisore di prova"
    assert body["decision"]["reason"] == ""


@pytest.mark.parametrize(
    "body", [{"status": "forse"}, {"status": "candidate", "reason": "a\x00b"}, {"reason": "x"}]
)
def test_invalid_decision_is_422(client: TestClient, engine: Engine, body: dict) -> None:
    tender = tender_with_report(engine)
    assert client.post(f"/api/tenders/{tender.id}/decision", json=body).status_code == 422


def field_to_verify(client: TestClient, engine: Engine) -> tuple[Tender, dict[str, Any]]:
    tender = tender_with_report(engine)
    body = client.get(f"/api/tenders/{tender.id}").json()
    field = next(f for f in body["report"]["fields"] if f["verification_status"] == "to_review")
    return tender, field


def test_confirm_report_field(client: TestClient, engine: Engine) -> None:
    tender, field = field_to_verify(client, engine)
    response = client.patch(
        f"/api/tenders/{tender.id}/report/fields/{field['id']}",
        json={"verification_status": "verified"},
        headers={"X-User-Name": "Bruno"},
    )
    assert response.status_code == 200
    updated = next(f for f in response.json()["report"]["fields"] if f["id"] == field["id"])
    assert updated["verification_status"] == "verified"
    assert updated["reviewer"] == "Bruno" and updated["corrected"] is False
    assert updated["value"] == field["value"]


def test_correct_report_field(client: TestClient, engine: Engine) -> None:
    tender, field = field_to_verify(client, engine)
    response = client.patch(
        f"/api/tenders/{tender.id}/report/fields/{field['id']}",
        json={"verification_status": "verified", "value": "Valore corretto"},
    )
    updated = next(f for f in response.json()["report"]["fields"] if f["id"] == field["id"])
    assert updated["value"] == "Valore corretto" and updated["corrected"] is True


@pytest.mark.parametrize(
    ("field_id", "body", "status"),
    [
        ("999999", {"verification_status": "verified"}, 404),
        ("x", {"verification_status": "verified"}, 404),
        (None, {"verification_status": "to_review"}, 422),
        (None, {"verification_status": "verified", "value": ""}, 422),
    ],
)
def test_invalid_field_update(
    client: TestClient, engine: Engine, field_id: str | None, body: dict, status: int
) -> None:
    tender, field = field_to_verify(client, engine)
    target = field_id or field["id"]
    response = client.patch(f"/api/tenders/{tender.id}/report/fields/{target}", json=body)
    assert response.status_code == status


def test_field_update_without_report_is_404(client: TestClient, engine: Engine) -> None:
    with session_of(engine) as s:
        tender = next(t for t in s.scalars(select(Tender)) if t.report is None)
    response = client.patch(
        f"/api/tenders/{tender.id}/report/fields/1", json={"verification_status": "verified"}
    )
    assert response.status_code == 404 and response.json()["error"] == "report_not_found"


def test_search(client: TestClient, engine: Engine) -> None:
    with session_of(engine) as s:
        tender = s.scalars(select(Tender).order_by(Tender.id)).first()
    assert tender is not None
    word = tender.title.split()[0]
    found = client.get("/api/search", params={"q": word}).json()
    assert str(tender.id) in {i["id"] for i in found}
    assert client.get("/api/search", params={"q": " "}).json() == []
    assert client.get("/api/search", params={"q": "a\x00"}).status_code == 422


def test_local_formats() -> None:
    moment = datetime(2026, 10, 25, 10, 30, tzinfo=UTC)  # dopo il cambio dell'ora: +01:00
    assert frontend.local_minutes(moment) == "2026-10-25T11:30"
    assert frontend.local_day(datetime(2026, 10, 15, 22, 30, tzinfo=UTC)) == "2026-10-16"
    assert frontend.local_minutes(None) is None and frontend.local_day(None) is None


def test_current_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRONTEND_DEFAULT_USER", raising=False)
    assert frontend.current_user(None) == frontend.DEFAULT_USER
    assert frontend.current_user("  Ada  ") == "Ada"
    assert len(frontend.current_user("x" * 300)) == 200


def test_digest_day_without_runs_is_yesterday(engine: Engine) -> None:
    with session_of(engine) as s:
        for run in s.scalars(select(IngestionRun)).all():
            s.delete(run)
        s.flush()
        assert frontend.digest_day(s, FIXED_NOW) == date(2026, 10, 14)
