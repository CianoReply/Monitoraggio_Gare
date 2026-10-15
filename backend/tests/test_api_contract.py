"""Verifica che docs/API_CONTRACT.yaml sia un documento OpenAPI valido (T0.5). Nessuna rete."""

from collections.abc import Iterator
from typing import Any

from openapi_schema_validator import OAS31Validator, oas31_format_checker
from openapi_spec_validator import validate

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


ERROR_REF = "#/components/schemas/Error"


def _resolve(spec: dict, node: Any) -> Any:
    """Risolve ricorsivamente i $ref locali (il contratto non ha riferimenti circolari)."""
    if isinstance(node, dict):
        if "$ref" in node:
            target: Any = spec
            for part in node["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            return _resolve(spec, target)
        return {key: _resolve(spec, value) for key, value in node.items()}
    if isinstance(node, list):
        return [_resolve(spec, value) for value in node]
    return node


def _operations(spec: dict) -> Iterator[tuple[str, str, dict]]:
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in HTTP_METHODS:
                yield method, path, op


def _examples(media: dict) -> list[Any]:
    found = [media["example"]] if "example" in media else []
    found += [ex["value"] for ex in media.get("examples", {}).values()]
    return found


def test_every_example_matches_its_schema(spec: dict) -> None:
    checked = 0
    for method, path, op in _operations(spec):
        medias = [("request", op.get("requestBody", {}).get("content", {}))]
        medias += [(code, resp.get("content", {})) for code, resp in op["responses"].items()]
        for where, content in medias:
            for media in content.values():
                schema = _resolve(spec, media["schema"])
                resolved = _resolve(spec, media)
                for example in _examples(resolved):
                    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
                    errors = [e.message for e in validator.iter_errors(example)]
                    assert not errors, f"{method} {path} [{where}]: {errors}"
                    checked += 1
    assert checked >= 15


def test_all_error_responses_use_error_schema(spec: dict) -> None:
    for method, path, op in _operations(spec):
        for code, resp in op["responses"].items():
            if not code.startswith("4"):
                continue
            raw = resp
            if "$ref" in raw:
                raw = spec["components"]["responses"][raw["$ref"].rsplit("/", 1)[1]]
            schema = raw["content"]["application/json"]["schema"]
            assert schema == {"$ref": ERROR_REF}, f"{method} {path} {code}"


def test_error_status_codes_cover_all_operations(spec: dict) -> None:
    for method, path, op in _operations(spec):
        codes = set(op["responses"])
        if "{id}" in path:
            assert "404" in codes, f"{method} {path}: manca 404"
        if "parameters" in op or "requestBody" in op:
            assert "422" in codes, f"{method} {path}: manca 422"
    assert "409" in spec["paths"]["/tenders/{id}/report"]["post"]["responses"]
    assert "409" in spec["paths"]["/runs"]["post"]["responses"]


def test_errors_use_single_format(spec: dict) -> None:
    error = spec["components"]["schemas"]["Error"]
    assert set(error["required"]) == {"error", "message"}


def test_field_review_requires_value_for_correct(spec: dict) -> None:
    schema = _resolve(spec, spec["components"]["schemas"]["FieldReview"])
    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
    assert validator.is_valid({"action": "confirm", "reviewer": "A"})
    assert validator.is_valid({"action": "correct", "value": "x", "reviewer": "A"})
    assert not validator.is_valid({"action": "correct", "reviewer": "A"})
    assert not validator.is_valid({"action": "confirm", "reviewer": "A", "extra": 1})
