"""Verifica che docs/API_CONTRACT.yaml sia un documento OpenAPI valido (T0.5). Nessuna rete."""

from pathlib import Path

import pytest
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "API_CONTRACT.yaml"

EXPECTED_OPERATIONS = {
    ("get", "/tenders"),
    ("get", "/tenders/{id}"),
    ("get", "/tenders/{id}/documents"),
    ("get", "/tenders/{id}/report"),
    ("post", "/tenders/{id}/report"),
    ("patch", "/reports/{id}/fields/{field_id}"),
    ("get", "/deadlines"),
    ("get", "/stats"),
    ("get", "/runs"),
    ("post", "/runs"),
    ("get", "/health"),
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def spec() -> dict:
    data, _ = read_from_filename(str(CONTRACT))
    return data


def test_contract_is_valid_openapi(spec: dict) -> None:
    validate(spec)


def test_contract_has_all_eleven_endpoints(spec: dict) -> None:
    found = {
        (method, path)
        for path, item in spec["paths"].items()
        for method in item
        if method in HTTP_METHODS
    }
    assert found == EXPECTED_OPERATIONS


def test_every_endpoint_has_example_and_success_response(spec: dict) -> None:
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in HTTP_METHODS:
                continue
            ok = [code for code in op["responses"] if code.startswith("2")]
            assert ok, f"{method} {path}: nessuna risposta di successo"
            content = op["responses"][ok[0]]["content"]["application/json"]
            assert "example" in content or "examples" in content, (
                f"{method} {path}: manca l'esempio"
            )


def test_error_codes_are_documented(spec: dict) -> None:
    paths = spec["paths"]
    assert "404" in paths["/tenders/{id}"]["get"]["responses"]
    assert "409" in paths["/tenders/{id}/report"]["post"]["responses"]
    assert "409" in paths["/runs"]["post"]["responses"]
    assert "202" in paths["/runs"]["post"]["responses"]
    assert "422" in paths["/tenders"]["get"]["responses"]


def test_errors_use_single_format(spec: dict) -> None:
    error = spec["components"]["schemas"]["Error"]
    assert error["required"] == ["error", "message"]
