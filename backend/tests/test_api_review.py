"""Test di PATCH /reports/{id}/fields/{field_id} (T3.4) con SQLite in memoria e seed.py."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS31Validator, oas31_format_checker
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.domain.database import create_session_factory
from backend.domain.models import Report, ReportStatus
from backend.tests.api_db import make_app, make_seeded_engine
from backend.tests.contract_utils import resolve

ROME = ZoneInfo("Europe/Rome")
LABEL_TO_REVIEW = "Contenuto generato con IA – da revisionare"


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


@pytest.fixture
def report(db: Session) -> Report:
    """Report `to_review` del seed: 2 campi critici e 1 non critico, tutti da verificare."""
    found = db.scalars(select(Report).where(Report.status == ReportStatus.TO_REVIEW)).first()
    assert found is not None
    assert sorted(f.is_critical for f in found.fields) == [False, True, True]
    return found


def _url(report: Report, field_id: int) -> str:
    return f"/reports/{report.id}/fields/{field_id}"


def _critical_ids(report: Report) -> list[int]:
    return [f.id for f in report.fields if f.is_critical]


def _field(body: dict, field_id: int) -> dict:
    return next(f for f in body["fields"] if f["id"] == field_id)


def _validate(spec: dict, body: Any) -> list[str]:
    media = spec["paths"]["/reports/{id}/fields/{field_id}"]["patch"]["responses"]["200"]
    schema = resolve(spec, media)["content"]["application/json"]["schema"]
    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
    return [e.message for e in validator.iter_errors(body)]


@pytest.mark.contract
def test_confirm_marks_field_verified_and_saves_reviewer(
    client: TestClient, report: Report, spec: dict
) -> None:
    field_id = _critical_ids(report)[0]
    response = client.patch(
        _url(report, field_id), json={"action": "confirm", "reviewer": "Giuseppe Rossi"}
    )
    assert response.status_code == 200
    body = response.json()
    assert _validate(spec, body) == []
    field = _field(body, field_id)
    assert field["verification_status"] == "verified"
    assert field["reviewer"] == "Giuseppe Rossi"
    assert field["original_value"] is None
    reviewed_at = datetime.fromisoformat(field["reviewed_at"])
    assert reviewed_at.utcoffset() is not None
    assert abs((datetime.now(reviewed_at.tzinfo) - reviewed_at).total_seconds()) < 60
    # Un solo campo critico confermato su due: il report resta da rivedere.
    assert body["status"] == "to_review"
    assert body["ai_label"] == LABEL_TO_REVIEW
    # Persistito: lo restituisce anche GET.
    assert client.get(f"/tenders/{report.tender_id}/report").json() == body


def test_confirming_all_critical_fields_makes_report_verified(
    client: TestClient, report: Report
) -> None:
    first, second = _critical_ids(report)
    step1 = client.patch(_url(report, first), json={"action": "confirm", "reviewer": "Anna"})
    assert step1.json()["status"] == "to_review"
    day_before = datetime.now(ROME).date().isoformat()
    step2 = client.patch(_url(report, second), json={"action": "confirm", "reviewer": "Bruno"})
    day_after = datetime.now(ROME).date().isoformat()
    body = step2.json()
    assert body["status"] == "verified"
    assert body["ai_label"] in {
        f"Contenuto generato con IA – revisionato da Bruno, {day_before}",
        f"Contenuto generato con IA – revisionato da Bruno, {day_after}",
    }
    assert client.get(f"/tenders/{report.tender_id}").json()["report_status"] == "verified"
    # Il campo non critico resta da verificare e non blocca lo stato del report.
    non_critical = next(f for f in body["fields"] if not f["is_critical"])
    assert non_critical["verification_status"] == "to_verify"


def test_correct_replaces_value_and_keeps_original(client: TestClient, report: Report) -> None:
    field = report.fields[0]
    original = field.value
    response = client.patch(
        _url(report, field.id),
        json={"action": "correct", "value": "2.450.000 EUR", "reviewer": "Giuseppe Rossi"},
    )
    assert response.status_code == 200
    item = _field(response.json(), field.id)
    assert item["value"] == "2.450.000 EUR"
    assert item["original_value"] == original
    assert item["verification_status"] == "verified"
    assert item["reviewer"] == "Giuseppe Rossi"


def test_second_correction_keeps_the_first_original_value(
    client: TestClient, report: Report
) -> None:
    field = report.fields[0]
    original = field.value
    url = _url(report, field.id)
    client.patch(url, json={"action": "correct", "value": "primo", "reviewer": "A"})
    response = client.patch(url, json={"action": "correct", "value": "secondo", "reviewer": "B"})
    item = _field(response.json(), field.id)
    assert (item["value"], item["original_value"], item["reviewer"]) == ("secondo", original, "B")


def test_confirm_after_correction_keeps_corrected_value_and_original(
    client: TestClient, report: Report
) -> None:
    field = report.fields[0]
    original = field.value
    url = _url(report, field.id)
    client.patch(url, json={"action": "correct", "value": "corretto", "reviewer": "A"})
    item = _field(client.patch(url, json={"action": "confirm", "reviewer": "B"}).json(), field.id)
    assert (item["value"], item["original_value"], item["reviewer"]) == ("corretto", original, "B")


def test_value_is_ignored_with_confirm(client: TestClient, report: Report) -> None:
    field = report.fields[0]
    original = field.value
    response = client.patch(
        _url(report, field.id), json={"action": "confirm", "value": "ignorato", "reviewer": "A"}
    )
    item = _field(response.json(), field.id)
    assert item["value"] == original
    assert item["original_value"] is None


def test_report_already_verified_stays_verified_on_non_critical_review(
    client: TestClient, db: Session
) -> None:
    verified = db.scalars(select(Report).where(Report.status == ReportStatus.VERIFIED)).first()
    assert verified is not None
    non_critical = next(f for f in verified.fields if not f.is_critical)
    response = client.patch(
        f"/reports/{verified.id}/fields/{non_critical.id}",
        json={"action": "confirm", "reviewer": "Carla"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"
    assert "revisionato da Carla" in response.json()["ai_label"]


def test_report_changes_do_not_leak_to_other_reports(client: TestClient, db: Session) -> None:
    reports = db.scalars(select(Report).order_by(Report.id)).all()
    target, other = reports[0], reports[1]
    before = client.get(f"/tenders/{other.tender_id}/report").json()
    client.patch(
        f"/reports/{target.id}/fields/{target.fields[0].id}",
        json={"action": "correct", "value": "x", "reviewer": "A"},
    )
    assert client.get(f"/tenders/{other.tender_id}/report").json() == before


@pytest.mark.parametrize(
    "body",
    [
        {"action": "correct", "reviewer": "A"},  # value obbligatorio con correct
        {"action": "correct", "value": "", "reviewer": "A"},
        {"action": "correct", "value": None, "reviewer": "A"},
        {"action": "confirm"},
        {"action": "confirm", "reviewer": ""},
        {"action": "confirm", "reviewer": "x" * 201},  # più lungo della colonna: 422, non 500
        {"action": "delete", "reviewer": "A"},
        {"action": "confirm", "reviewer": "A", "extra": 1},
        {"reviewer": "A"},
        {},
    ],
)
def test_invalid_review_is_422_and_changes_nothing(
    client: TestClient, report: Report, body: dict
) -> None:
    field_id = report.fields[0].id
    before = client.get(f"/tenders/{report.tender_id}/report").json()
    response = client.patch(_url(report, field_id), json=body)
    assert response.status_code == 422
    payload = response.json()
    assert set(payload) == {"error", "message"}
    assert payload["error"] == "validation_error"
    assert client.get(f"/tenders/{report.tender_id}/report").json() == before


def test_non_json_body_is_422(client: TestClient, report: Report) -> None:
    response = client.patch(
        _url(report, report.fields[0].id),
        content="non json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_unknown_report_is_404(client: TestClient) -> None:
    response = client.patch("/reports/99999/fields/1", json={"action": "confirm", "reviewer": "A"})
    assert response.status_code == 404
    assert response.json() == {
        "error": "report_not_found",
        "message": "Il report 99999 non esiste.",
    }


def test_unknown_field_is_404(client: TestClient, report: Report) -> None:
    response = client.patch(_url(report, 99999), json={"action": "confirm", "reviewer": "A"})
    assert response.status_code == 404
    assert response.json() == {
        "error": "field_not_found",
        "message": f"Il campo 99999 non appartiene al report {report.id}.",
    }


def test_field_of_another_report_is_404(client: TestClient, db: Session) -> None:
    first, second = db.scalars(select(Report).order_by(Report.id)).all()[:2]
    foreign_field = second.fields[0].id
    response = client.patch(
        f"/reports/{first.id}/fields/{foreign_field}",
        json={"action": "confirm", "reviewer": "A"},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "field_not_found"


@pytest.mark.parametrize(
    "path", ["/reports/0/fields/1", "/reports/1/fields/0", "/reports/-1/fields/1"]
)
def test_non_positive_ids_are_422(client: TestClient, path: str) -> None:
    response = client.patch(path, json={"action": "confirm", "reviewer": "A"})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
