"""Test dello scheletro dell'API (T3.1): contratto, errori, CORS. Senza rete."""

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS31Validator, oas31_format_checker

from backend.api.errors import ApiError, error_responses
from backend.api.main import create_app
from backend.tests.api_db import make_app, make_seeded_engine
from backend.tests.contract_utils import HTTP_METHODS, resolve

pytestmark = pytest.mark.contract

# GET /tenders legge dal database (T3.2): qui un SQLite in memoria con i dati di seed.
app = make_app(make_seeded_engine())
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

REPORT_FIELD = {"label": "Importo", "value": "1 EUR", "source_doc": "a.pdf", "is_critical": True}
REPORT_BODY = {"summary": "Sintesi", "fields": [REPORT_FIELD]}

# Chiavi di JSON Schema confrontate tra contratto e documentazione generata da FastAPI.
COMPARED_KEYS = {
    "type",
    "format",
    "enum",
    "default",
    "pattern",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "required",
    "additionalProperties",
}

# Differenza nota e non eliminabile (limite di FastAPI/Pydantic): il contratto impone `value`
# con `action=correct` tramite if/then in FieldReview, che Pydantic non sa emettere; la regola
# è applicata da un validatore (vedi test_invalid_review_body_returns_422).
KNOWN_CONTRACT_ONLY_KEYS = {"if", "then"}


def _contract_path(url: str) -> str:
    """Converte un URL concreto nel percorso del contratto (es. /tenders/101 -> /tenders/{id})."""
    parts = url.split("/")
    if len(parts) > 2 and parts[1] == "tenders":
        parts[2] = "{id}"
    return "/".join(parts)


def _assert_matches_contract(spec: dict, method: str, path: str, response: Any) -> None:
    op = spec["paths"][path][method]
    media = op["responses"][str(response.status_code)]
    schema = resolve(spec, media)["content"]["application/json"]["schema"]
    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
    errors = [e.message for e in validator.iter_errors(response.json())]
    assert not errors, f"{method} {path} {response.status_code}: {errors}"


def _normalize(spec: dict, node: Any) -> Any:
    """Riduce uno schema alle sole chiavi confrontate, uguali tra contratto e FastAPI.

    Risolve i $ref, toglie titoli e descrizioni, elimina `null` da `type` e da `anyOf`
    (la nullabilità dei parametri è irrilevante: sono comunque opzionali), traduce `const`
    in `enum` e un `default: null` nell'assenza di default.
    """
    node = resolve(spec, node)
    if not isinstance(node, dict):
        return node
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        assert len(options) == 1, node
        merged = {**{k: v for k, v in node.items() if k != "anyOf"}, **options[0]}
        return _normalize(spec, merged)
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "const":
            out["enum"] = [value]
        elif key == "type" and isinstance(value, list):
            out["type"] = [t for t in value if t != "null"][0]
        elif key == "default" and value is None:
            continue
        elif key in COMPARED_KEYS:
            out[key] = sorted(value) if key == "required" else value
        elif key == "items":
            out["items"] = _normalize(spec, value)
        elif key == "properties":
            out["properties"] = {name: _normalize(spec, sub) for name, sub in value.items()}
    return out


def _body_schema(doc: dict, media: dict) -> Any:
    return _normalize(doc, resolve(doc, media)["content"]["application/json"]["schema"])


def _params(doc: dict, op: dict) -> dict:
    return {
        (p["in"], p["name"]): (
            p["in"] == "path" or p.get("required", False),
            _normalize(doc, p["schema"]),
        )
        for p in resolve(doc, op).get("parameters", [])
    }


@pytest.mark.parametrize(("method", "url", "status"), ENDPOINTS)
def test_endpoint_returns_sample_data_conforming_to_contract(
    spec: dict, method: str, url: str, status: int
) -> None:
    response = client.request(method, url)
    assert response.status_code == status
    _assert_matches_contract(spec, method, _contract_path(url), response)


def test_post_report_and_patch_field_conform_to_contract(spec: dict) -> None:
    created = client.post("/tenders/102/report", json=REPORT_BODY)
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
        assert set(generated_op["responses"]) == set(contract_op["responses"]), key
        assert ("requestBody" in generated_op) == ("requestBody" in contract_op), key

        # Parametri: nome, posizione, obbligatorietà e schema (type, minimum, default, ...).
        assert _params(generated, generated_op) == _params(spec, contract_op), key

        # Corpo della richiesta.
        if "requestBody" in contract_op:
            assert _body_schema(generated, generated_op["requestBody"]) == _body_schema(
                spec, contract_op["requestBody"]
            ), key

        # Risposte di successo.
        for code, contract_resp in contract_op["responses"].items():
            if code.startswith("2"):
                assert _body_schema(generated, generated_op["responses"][code]) == _body_schema(
                    spec, contract_resp
                ), (key, code)


def test_known_contract_only_keys_are_only_on_field_review(spec: dict) -> None:
    for name, schema in spec["components"]["schemas"].items():
        found = KNOWN_CONTRACT_ONLY_KEYS & set(schema)
        assert not found or name == "FieldReview", name


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
    response = client.post("/tenders/101/report", json=REPORT_BODY)
    assert response.status_code == 409
    assert response.json()["error"] == "report_already_exists"


def test_api_error_409_run_in_progress_uses_error_format() -> None:
    test_app = create_app()
    router = APIRouter()

    @router.post("/busy")
    def busy() -> None:
        raise ApiError(409, "run_in_progress", "L'esecuzione 32 è già in corso.")

    test_app.include_router(router)
    response = TestClient(test_app).post("/busy")
    assert response.status_code == 409
    assert response.json() == {
        "error": "run_in_progress",
        "message": "L'esecuzione 32 è già in corso.",
    }


@pytest.mark.parametrize(
    ("url", "prefix"),
    [
        ("/tenders?page_size=101", "page_size: "),
        ("/tenders?page=0", "page: "),
        ("/tenders?min_score=6", "min_score: "),
        ("/tenders?cpv=abc", "cpv: "),
        ("/tenders?sort=unknown", "sort: "),
        ("/tenders?deadline_from=2026-11-10&deadline_to=2026-11-01", "deadline_from"),
        ("/tenders?min_value=10&max_value=5", "min_value"),
        ("/tenders/abc", "id: "),
        ("/tenders/0", "id: "),
        ("/tenders/0/report", "id: "),
        ("/reports/0/fields/1", "id: "),
        ("/reports/7/fields/0", "field_id: "),
        ("/deadlines?from=2026-11-10&to=2026-11-01", "to "),
        ("/deadlines?from=not-a-date", "from: "),
        ("/runs?limit=0", "limit: "),
    ],
)
def test_invalid_parameters_return_422_in_error_format(url: str, prefix: str) -> None:
    if url.startswith("/reports"):
        response = client.patch(url, json={"action": "confirm", "reviewer": "A"})
    else:
        response = client.get(url)
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error", "message"}
    assert body["error"] == "validation_error"
    assert body["message"].startswith(prefix)


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


@pytest.mark.parametrize(
    "body",
    [
        {"summary": "x", "fields": []},
        {**REPORT_BODY, "generated_at": None},
        {**REPORT_BODY, "extra": 1},
        {"summary": "x", "fields": [{**REPORT_FIELD, "extra": 1}]},
    ],
)
def test_invalid_report_body_returns_422(body: dict) -> None:
    response = client.post("/tenders/102/report", json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


def test_report_accepts_explicit_generated_at() -> None:
    body = {**REPORT_BODY, "generated_at": "2026-10-14T09:15:00+00:00"}
    assert client.post("/tenders/102/report", json=body).status_code == 201


def test_deadlines_accepts_from_parameter() -> None:
    response = client.get("/deadlines", params={"from": "2026-10-15", "to": "2026-11-15"})
    assert response.status_code == 200


def test_method_not_allowed_uses_error_format() -> None:
    response = client.delete("/tenders/101")
    assert response.status_code == 405
    assert response.json()["error"] == "method_not_allowed"


def test_unhandled_exception_returns_500_without_details() -> None:
    test_app = create_app()
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("segreto interno")

    test_app.include_router(router)
    response = TestClient(test_app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": "internal_error",
        "message": "Errore interno del server.",
    }


def test_cors_allows_frontend_origin() -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_is_allowed_for_frontend_origin() -> None:
    response = client.options(
        "/tenders/102/report",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_cors_rejects_unknown_origin() -> None:
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_come_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://radar.example, https://altro.example")
    custom = TestClient(create_app())
    ok = custom.get("/health", headers={"Origin": "https://altro.example"})
    assert ok.headers["access-control-allow-origin"] == "https://altro.example"
    refused = custom.get("/health", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" not in refused.headers


def test_create_app_returns_independent_instances() -> None:
    first, second = create_app(), create_app()
    assert isinstance(first, FastAPI)
    assert first is not second
    assert {"/health", "/tenders", "/runs"} <= set(first.openapi()["paths"])


def test_error_responses_declares_error_model() -> None:
    declared = error_responses(404, 422)
    assert set(declared) == {404, 422}
    assert declared[404]["model"].__name__ == "Error"
    assert declared[404] == declared[422]
