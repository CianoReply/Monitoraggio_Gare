"""Test dello scheletro dell'API (T3.1): dati di prova, contratto ed errori. Senza rete."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS31Validator, oas31_format_checker

from backend.api.main import app
from backend.tests.test_api_contract import HTTP_METHODS, _resolve

client = TestClient(app)

ENDPOINTS: list[tuple[str, str, int]] = [
    ("get", "/tenders", 200),
    ("get", "/tenders/101", 200),
    ("get", "/tenders/101/documents", 200),
    ("get", "/tenders/101/report", 200),
    ("get", "/deadlines", 200),
    ("get", "/stats", 200),
    ("get", "/runs", 200),
    ("post", "/runs", 202),
    ("get", "/health", 200),
]


def _contract_path(url: str) -> str:
    """Converte un URL concreto nel percorso del contratto (es. /tenders/101 -> /tenders/{id})."""
    parts = url.split("/")
    if len(parts) > 2 and parts[1] == "tenders":
        parts[2] = "{id}"
    return "/".join(parts)


def _assert_matches_contract(spec: dict, method: str, path: str, response: Any) -> None:
    op = spec["paths"][path][method]
    media = op["responses"][str(response.status_code)]
    schema = _resolve(spec, media)["content"]["application/json"]["schema"]
    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
    errors = [e.message for e in validator.iter_errors(response.json())]
    assert not errors, f"{method} {path} {response.status_code}: {errors}"


@pytest.mark.parametrize(("method", "url", "status"), ENDPOINTS)
def test_endpoint_returns_sample_data_conforming_to_contract(
    spec: dict, method: str, url: str, status: int
) -> None:
    response = client.request(method, url)
    assert response.status_code == status
    _assert_matches_contract(spec, method, _contract_path(url), response)


def test_post_report_and_patch_field_conform_to_contract(spec: dict) -> None:
    body = {
        "summary": "Sintesi",
        "fields": [
            {"label": "Importo", "value": "1 EUR", "source_doc": "a.pdf", "is_critical": True}
        ],
    }
    created = client.post("/tenders/102/report", json=body)
    assert created.status_code == 201
    _assert_matches_contract(spec, "post", "/tenders/{id}/report", created)

    reviewed = client.patch("/reports/7/fields/71", json={"action": "confirm", "reviewer": "A"})
    assert reviewed.status_code == 200
    _assert_matches_contract(spec, "patch", "/reports/{id}/fields/{field_id}", reviewed)


def test_openapi_docs_match_contract(spec: dict) -> None:
    generated = app.openapi()
    contract_ops = {
        (m, p): op
        for p, item in spec["paths"].items()
        for m, op in item.items()
        if m in HTTP_METHODS
    }
    generated_ops = {(m, p): op for p, item in generated["paths"].items() for m, op in item.items()}
    assert set(generated_ops) == set(contract_ops)

    for key, contract_op in contract_ops.items():
        generated_op = generated_ops[key]
        expected_params = {
            (p["in"], p["name"], p["in"] == "path" or p.get("required", False))
            for p in _resolve(spec, contract_op).get("parameters", [])
        }
        actual_params = {
            (p["in"], p["name"], p.get("required", False))
            for p in generated_op.get("parameters", [])
        }
        assert actual_params == expected_params, key
        assert set(generated_op["responses"]) == set(contract_op["responses"]), key
        assert ("requestBody" in generated_op) == ("requestBody" in contract_op), key


def test_not_found_uses_error_format() -> None:
    for url in ("/tenders/999", "/tenders/999/documents", "/tenders/999/report"):
        response = client.get(url)
        assert response.status_code == 404
        assert response.json() == {
            "error": "tender_not_found",
            "message": "La gara 999 non esiste.",
        }
    assert client.get("/tenders/102/report").json()["error"] == "report_not_found"
    assert client.get("/nonexistent").json()["error"] == "not_found"
    patch = client.patch("/reports/7/fields/999", json={"action": "confirm", "reviewer": "A"})
    assert patch.status_code == 404
    assert patch.json()["error"] == "field_not_found"
    patch = client.patch("/reports/99/fields/71", json={"action": "confirm", "reviewer": "A"})
    assert patch.json()["error"] == "report_not_found"


def test_second_report_returns_409() -> None:
    body = {
        "summary": "Sintesi",
        "fields": [
            {"label": "Importo", "value": "1 EUR", "source_doc": "a.pdf", "is_critical": True}
        ],
    }
    response = client.post("/tenders/101/report", json=body)
    assert response.status_code == 409
    assert response.json()["error"] == "report_already_exists"


@pytest.mark.parametrize(
    "url",
    [
        "/tenders?page_size=101",
        "/tenders?page=0",
        "/tenders?min_score=6",
        "/tenders?cpv=abc",
        "/tenders?sort=unknown",
        "/tenders?deadline_from=2026-11-10&deadline_to=2026-11-01",
        "/tenders?min_value=10&max_value=5",
        "/tenders/abc",
        "/deadlines?from=2026-11-10&to=2026-11-01",
        "/deadlines?from=not-a-date",
        "/runs?limit=0",
    ],
)
def test_invalid_parameters_return_422_in_error_format(url: str) -> None:
    response = client.get(url)
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error", "message"}
    assert body["error"] == "validation_error"
    assert body["message"]


@pytest.mark.parametrize(
    "body",
    [
        {"action": "correct", "reviewer": "A"},
        {"action": "confirm"},
        {"action": "delete", "reviewer": "A"},
        {"action": "confirm", "reviewer": "A", "extra": 1},
    ],
)
def test_invalid_review_body_returns_422(body: dict) -> None:
    response = client.patch("/reports/7/fields/71", json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_invalid_report_body_returns_422() -> None:
    response = client.post("/tenders/102/report", json={"summary": "x", "fields": []})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_deadlines_accepts_from_parameter() -> None:
    response = client.get("/deadlines", params={"from": "2026-10-15", "to": "2026-11-15"})
    assert response.status_code == 200


def test_cors_allows_frontend_origin() -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
