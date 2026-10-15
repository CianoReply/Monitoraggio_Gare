"""Test di dettaglio gara, documenti e report (T3.3) con SQLite in memoria e seed.py. Senza rete.

Le attese si ricavano dal database con query indipendenti dall'API.
"""

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS31Validator, oas31_format_checker
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.domain.database import create_session_factory
from backend.domain.models import Document, Report, Tender
from backend.tests.api_db import make_app, make_seeded_engine
from backend.tests.contract_utils import resolve

REPORT_BODY: dict[str, Any] = {
    "summary": "Sintesi del bando di prova.",
    "generated_at": "2026-10-14T09:15:00+00:00",
    "fields": [
        {
            "label": "Importo a base di gara",
            "value": "890.000 EUR",
            "source_doc": "Disciplinare.pdf",
            "source_page": 2,
            "is_critical": True,
        },
        {"label": "Criterio", "value": "OEPV", "source_doc": "Bando.pdf", "is_critical": False},
    ],
}


@pytest.fixture
def engine() -> Engine:
    return make_seeded_engine()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    return TestClient(make_app(engine))


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with create_session_factory(engine)() as session:
        yield session


def _tender_without_report(db: Session) -> Tender:
    return db.scalars(
        select(Tender).outerjoin(Report).where(Report.id.is_(None)).order_by(Tender.id)
    ).first()  # type: ignore[return-value]


def _tender_with_report(db: Session) -> Tender:
    return db.scalars(select(Tender).join(Report).order_by(Tender.id)).first()  # type: ignore[return-value]


def _tender_with_documents(db: Session) -> Tender:
    return db.scalars(select(Tender).join(Document).order_by(Tender.id)).first()  # type: ignore[return-value]


def _tender_without_documents(db: Session) -> Tender:
    return db.scalars(
        select(Tender).outerjoin(Document).where(Document.id.is_(None)).order_by(Tender.id)
    ).first()  # type: ignore[return-value]


def _validate(spec: dict, path: str, method: str, code: str, body: Any) -> list[str]:
    media = spec["paths"][path][method]["responses"][code]
    schema = resolve(spec, media)["content"]["application/json"]["schema"]
    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
    return [e.message for e in validator.iter_errors(body)]


# --- GET /tenders/{id} ---


@pytest.mark.contract
def test_tender_detail_matches_database_and_contract(
    client: TestClient, db: Session, spec: dict
) -> None:
    tender = _tender_with_report(db)
    response = client.get(f"/tenders/{tender.id}")
    assert response.status_code == 200
    body = response.json()
    assert _validate(spec, "/tenders/{id}", "get", "200", body) == []
    assert body["id"] == tender.id
    assert body["publication_number"] == tender.publication_number
    assert body["title"] == tender.title
    assert body["cpv_codes"] == tender.cpv_codes
    assert body["relevance_score"] == tender.relevance_score
    assert body["report_status"] == tender.report.status.value


def test_tender_detail_report_status_none_without_report(client: TestClient, db: Session) -> None:
    tender = _tender_without_report(db)
    assert client.get(f"/tenders/{tender.id}").json()["report_status"] == "none"


def test_tender_detail_is_same_as_list_item(client: TestClient, db: Session) -> None:
    items = client.get("/tenders", params={"page_size": 100, "include_discarded": True}).json()
    for item in items["items"][:5]:
        assert client.get(f"/tenders/{item['id']}").json() == item


def test_tender_detail_returns_discarded_tender(client: TestClient, db: Session) -> None:
    discarded = db.scalars(select(Tender).where(Tender.discard_reason.is_not(None))).first()
    assert discarded is not None
    body = client.get(f"/tenders/{discarded.id}").json()
    assert body["discard_reason"] == discarded.discard_reason
    assert body["is_relevant"] is False


@pytest.mark.parametrize("tender_id", [99999, 1000000])
def test_tender_detail_unknown_id_is_404(client: TestClient, tender_id: int) -> None:
    response = client.get(f"/tenders/{tender_id}")
    assert response.status_code == 404
    assert response.json() == {
        "error": "tender_not_found",
        "message": f"La gara {tender_id} non esiste.",
    }


@pytest.mark.parametrize("tender_id", ["0", "-1", "abc"])
def test_tender_detail_invalid_id_is_422(client: TestClient, tender_id: str) -> None:
    response = client.get(f"/tenders/{tender_id}")
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


# --- GET /tenders/{id}/documents ---


@pytest.mark.contract
def test_documents_match_database_and_contract(client: TestClient, db: Session, spec: dict) -> None:
    tender = _tender_with_documents(db)
    response = client.get(f"/tenders/{tender.id}/documents")
    assert response.status_code == 200
    body = response.json()
    assert _validate(spec, "/tenders/{id}/documents", "get", "200", body) == []
    expected = db.scalars(
        select(Document).where(Document.tender_id == tender.id).order_by(Document.id)
    ).all()
    assert expected
    assert [(d["id"], d["name"], d["url"], d["status"]) for d in body["items"]] == [
        (d.id, d.name, d.url, d.status.value) for d in expected
    ]
    assert all(d["tender_id"] == tender.id for d in body["items"])


def test_documents_empty_for_tender_without_documents(client: TestClient, db: Session) -> None:
    tender = _tender_without_documents(db)
    response = client.get(f"/tenders/{tender.id}/documents")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_documents_include_status_paths_and_timezone(client: TestClient, db: Session) -> None:
    tender = _tender_with_documents(db)
    document = db.scalars(select(Document).where(Document.tender_id == tender.id)).first()
    assert document is not None
    document.status = type(document.status).DOWNLOADED
    document.local_path = "/data/documents/x/Disciplinare.pdf"
    document.downloaded_at = datetime(2026, 10, 12, 6, 41)  # SQLite lo restituisce senza fuso
    db.commit()
    item = next(
        d
        for d in client.get(f"/tenders/{tender.id}/documents").json()["items"]
        if d["id"] == document.id
    )
    assert item["status"] == "downloaded"
    assert item["local_path"] == "/data/documents/x/Disciplinare.pdf"
    parsed = datetime.fromisoformat(item["downloaded_at"])
    assert parsed.utcoffset() is not None
    assert parsed.isoformat() == "2026-10-12T06:41:00+00:00"


def test_documents_unknown_tender_is_404(client: TestClient) -> None:
    response = client.get("/tenders/99999/documents")
    assert response.status_code == 404
    assert response.json()["error"] == "tender_not_found"


def test_documents_invalid_id_is_422(client: TestClient) -> None:
    assert client.get("/tenders/0/documents").status_code == 422


# --- GET /tenders/{id}/report ---


@pytest.mark.contract
def test_report_matches_database_and_contract(client: TestClient, db: Session, spec: dict) -> None:
    tender = _tender_with_report(db)
    response = client.get(f"/tenders/{tender.id}/report")
    assert response.status_code == 200
    body = response.json()
    assert _validate(spec, "/tenders/{id}/report", "get", "200", body) == []
    report = tender.report
    assert (body["id"], body["tender_id"], body["status"]) == (
        report.id,
        tender.id,
        report.status.value,
    )
    assert body["summary"] == report.summary
    assert body["ai_label"] == report.ai_label
    assert [
        (f["id"], f["label"], f["value"], f["source_doc"], f["source_page"], f["is_critical"])
        for f in body["fields"]
    ] == [
        (f.id, f.label, f.value, f.source_doc, f.source_page, f.is_critical) for f in report.fields
    ]
    assert [f["verification_status"] for f in body["fields"]] == [
        f.verification_status.value for f in report.fields
    ]
    assert datetime.fromisoformat(body["generated_at"]).utcoffset() is not None


def test_reviewed_field_exposes_reviewer_original_value_and_timezone(
    client: TestClient, db: Session
) -> None:
    report = db.scalars(select(Report).where(Report.status == "verified")).first()
    assert report is not None
    field = report.fields[0]
    field.reviewer = "Mario Rossi"
    field.original_value = "valore della Skill"
    field.reviewed_at = datetime(2026, 10, 15, 8, 30)  # SQLite lo restituisce senza fuso
    db.commit()
    body = client.get(f"/tenders/{report.tender_id}/report").json()
    assert body["status"] == "verified"
    item = next(f for f in body["fields"] if f["id"] == field.id)
    assert item["reviewer"] == "Mario Rossi"
    assert item["original_value"] == "valore della Skill"
    assert datetime.fromisoformat(item["reviewed_at"]).isoformat() == "2026-10-15T08:30:00+00:00"


def test_report_missing_distinguishes_tender_and_report(client: TestClient, db: Session) -> None:
    tender = _tender_without_report(db)
    no_report = client.get(f"/tenders/{tender.id}/report")
    assert no_report.status_code == 404
    assert no_report.json() == {
        "error": "report_not_found",
        "message": f"La gara {tender.id} non ha ancora un report.",
    }
    no_tender = client.get("/tenders/99999/report")
    assert no_tender.status_code == 404
    assert no_tender.json()["error"] == "tender_not_found"


# --- POST /tenders/{id}/report ---


@pytest.mark.contract
def test_post_report_creates_it_and_persists(client: TestClient, db: Session, spec: dict) -> None:
    tender = _tender_without_report(db)
    response = client.post(f"/tenders/{tender.id}/report", json=REPORT_BODY)
    assert response.status_code == 201
    body = response.json()
    assert _validate(spec, "/tenders/{id}/report", "post", "201", body) == []
    assert body["tender_id"] == tender.id
    assert body["status"] == "to_review"
    assert body["ai_label"] == "Contenuto generato con IA – da revisionare"
    assert body["generated_at"] == "2026-10-14T09:15:00Z" or datetime.fromisoformat(
        body["generated_at"]
    ) == datetime.fromisoformat("2026-10-14T09:15:00+00:00")
    assert [f["verification_status"] for f in body["fields"]] == ["to_verify", "to_verify"]
    assert [f["source_page"] for f in body["fields"]] == [2, None]
    assert all(f["reviewer"] is None and f["original_value"] is None for f in body["fields"])

    # Salvato davvero (commit): lo restituisce GET e il filtro per stato del report.
    assert client.get(f"/tenders/{tender.id}/report").json() == body
    assert client.get(f"/tenders/{tender.id}").json()["report_status"] == "to_review"


def test_post_report_without_generated_at_uses_now(client: TestClient, db: Session) -> None:
    tender = _tender_without_report(db)
    payload = {k: v for k, v in REPORT_BODY.items() if k != "generated_at"}
    response = client.post(f"/tenders/{tender.id}/report", json=payload)
    assert response.status_code == 201
    generated = datetime.fromisoformat(response.json()["generated_at"])
    assert generated.utcoffset() is not None
    assert abs((datetime.now(generated.tzinfo) - generated).total_seconds()) < 60


def test_second_post_returns_409_and_keeps_first_report(client: TestClient, db: Session) -> None:
    tender = _tender_without_report(db)
    first = client.post(f"/tenders/{tender.id}/report", json=REPORT_BODY)
    other = {**REPORT_BODY, "summary": "Altro"}
    second = client.post(f"/tenders/{tender.id}/report", json=other)
    assert second.status_code == 409
    assert second.json() == {
        "error": "report_already_exists",
        "message": f"La gara {tender.id} ha già un report.",
    }
    assert client.get(f"/tenders/{tender.id}/report").json() == first.json()


def test_post_on_tender_with_seed_report_returns_409(client: TestClient, db: Session) -> None:
    tender = _tender_with_report(db)
    assert client.post(f"/tenders/{tender.id}/report", json=REPORT_BODY).status_code == 409


def test_post_unknown_tender_is_404(client: TestClient) -> None:
    response = client.post("/tenders/99999/report", json=REPORT_BODY)
    assert response.status_code == 404
    assert response.json()["error"] == "tender_not_found"


def _bad_bodies() -> list[Any]:
    long_label = {**REPORT_BODY["fields"][0], "label": "x" * 201}
    return [
        {"fields": REPORT_BODY["fields"]},  # summary mancante
        {**REPORT_BODY, "summary": ""},
        {**REPORT_BODY, "fields": []},
        {**REPORT_BODY, "extra": 1},
        {**REPORT_BODY, "generated_at": None},
        {**REPORT_BODY, "generated_at": "2026-10-14T09:15:00"},  # senza fuso orario
        {**REPORT_BODY, "generated_at": "ieri"},
        {**REPORT_BODY, "fields": [{**REPORT_BODY["fields"][0], "source_page": 0}]},
        {**REPORT_BODY, "fields": [{**REPORT_BODY["fields"][0], "is_critical": "si"}]},
        {**REPORT_BODY, "fields": [{**REPORT_BODY["fields"][0], "extra": 1}]},
        {**REPORT_BODY, "fields": [long_label]},  # più lungo della colonna: 422, non 500
        {**REPORT_BODY, "fields": [{"label": "a"}]},
    ]


@pytest.mark.parametrize("body", _bad_bodies())
def test_invalid_report_is_422_and_not_saved(client: TestClient, db: Session, body: Any) -> None:
    tender = _tender_without_report(db)
    response = client.post(f"/tenders/{tender.id}/report", json=body)
    assert response.status_code == 422
    payload = response.json()
    assert set(payload) == {"error", "message"}
    assert payload["error"] == "validation_error"
    assert payload["message"]
    assert client.get(f"/tenders/{tender.id}/report").status_code == 404


def test_post_non_json_body_is_422(client: TestClient, db: Session) -> None:
    tender = _tender_without_report(db)
    response = client.post(
        f"/tenders/{tender.id}/report",
        content="non json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_post_invalid_id_is_422(client: TestClient) -> None:
    assert client.post("/tenders/0/report", json=REPORT_BODY).status_code == 422
