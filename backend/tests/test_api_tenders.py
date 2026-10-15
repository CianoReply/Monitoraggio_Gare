"""Test di GET /tenders con database reale (SQLite in memoria + seed.py), T3.2. Senza rete.

Le attese si calcolano in Python dall'elenco completo, indipendentemente dal repository.
"""

from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS31Validator, oas31_format_checker

from backend.api import tenders as tenders_module
from backend.domain.repository import InvalidQueryError
from backend.tests.api_db import make_app, make_seeded_engine
from backend.tests.contract_utils import resolve

ROME = ZoneInfo("Europe/Rome")


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    yield TestClient(make_app(make_seeded_engine()))


def _get(client: TestClient, **params: Any) -> dict:
    response = client.get("/tenders", params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def everything(client: TestClient) -> list[dict]:
    """Tutte le gare del seed, scartate comprese."""
    body = _get(client, include_discarded=True, page_size=100)
    assert body["total"] == len(body["items"])
    return body["items"]


def _ids(body: dict) -> list[int]:
    return [item["id"] for item in body["items"]]


def _expected_ids(everything: list[dict], keep: Callable[[dict], bool]) -> set[int]:
    return {t["id"] for t in everything if keep(t)}


def _deadline_day(tender: dict) -> Any:
    return datetime.fromisoformat(tender["submission_deadline"]).astimezone(ROME).date()


@pytest.mark.contract
def test_response_conforms_to_contract(client: TestClient, spec: dict) -> None:
    response = client.get("/tenders")
    assert response.status_code == 200
    op = spec["paths"]["/tenders"]["get"]["responses"]["200"]
    schema = resolve(spec, op)["content"]["application/json"]["schema"]
    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
    assert [e.message for e in validator.iter_errors(response.json())] == []
    body = response.json()
    assert (body["page"], body["page_size"]) == (1, 20)
    assert all(item["relevance_score"] in range(1, 6) for item in body["items"])


def test_seed_contains_discarded_and_reports(everything: list[dict]) -> None:
    """Precondizioni dei test sui filtri: i dati di seed devono essere abbastanza vari."""
    assert len(everything) == 20
    assert any(t["discard_reason"] for t in everything)
    assert {"none", "to_review", "verified"} <= {t["report_status"] for t in everything}
    assert any(t["estimated_value"] is None for t in everything)


def test_default_excludes_discarded_and_include_discarded_adds_them(
    client: TestClient, everything: list[dict]
) -> None:
    body = _get(client, page_size=100)
    assert set(_ids(body)) == _expected_ids(everything, lambda t: t["discard_reason"] is None)
    assert all(t["discard_reason"] is None for t in body["items"])
    assert body["total"] < len(everything)


def test_filter_min_score(client: TestClient, everything: list[dict]) -> None:
    body = _get(client, min_score=4, include_discarded=True, page_size=100)
    assert set(_ids(body)) == _expected_ids(everything, lambda t: t["relevance_score"] >= 4)
    assert body["total"] == len(body["items"]) > 0


def test_filter_cpv_prefix(client: TestClient, everything: list[dict]) -> None:
    body = _get(client, cpv="722", include_discarded=True, page_size=100)
    expected = _expected_ids(everything, lambda t: any(c.startswith("722") for c in t["cpv_codes"]))
    assert set(_ids(body)) == expected
    assert 0 < len(expected) < len(everything)


def test_filter_deadline_range(client: TestClient, everything: list[dict]) -> None:
    days = sorted({_deadline_day(t) for t in everything if t["submission_deadline"]})
    lo, hi = days[len(days) // 3], days[2 * len(days) // 3]
    body = _get(
        client,
        deadline_from=lo.isoformat(),
        deadline_to=hi.isoformat(),
        include_discarded=True,
        page_size=100,
    )
    expected = _expected_ids(
        everything, lambda t: bool(t["submission_deadline"]) and lo <= _deadline_day(t) <= hi
    )
    assert set(_ids(body)) == expected
    assert expected


def test_filter_deadline_from_and_to_alone(client: TestClient, everything: list[dict]) -> None:
    days = sorted({_deadline_day(t) for t in everything if t["submission_deadline"]})
    mid = days[len(days) // 2]
    only_from = _get(client, deadline_from=mid.isoformat(), include_discarded=True, page_size=100)
    assert set(_ids(only_from)) == _expected_ids(
        everything, lambda t: bool(t["submission_deadline"]) and _deadline_day(t) >= mid
    )
    only_to = _get(client, deadline_to=mid.isoformat(), include_discarded=True, page_size=100)
    assert set(_ids(only_to)) == _expected_ids(
        everything, lambda t: bool(t["submission_deadline"]) and _deadline_day(t) <= mid
    )


def test_filter_value_range_excludes_tenders_without_value(
    client: TestClient, everything: list[dict]
) -> None:
    body = _get(client, min_value=100000, max_value=1000000, include_discarded=True, page_size=100)
    expected = _expected_ids(
        everything,
        lambda t: t["estimated_value"] is not None and 100000 <= t["estimated_value"] <= 1000000,
    )
    assert set(_ids(body)) == expected
    assert expected
    only_min = _get(client, min_value=1000000, include_discarded=True, page_size=100)
    assert set(_ids(only_min)) == _expected_ids(
        everything, lambda t: t["estimated_value"] is not None and t["estimated_value"] >= 1000000
    )
    only_max = _get(client, max_value=100000, include_discarded=True, page_size=100)
    assert set(_ids(only_max)) == _expected_ids(
        everything, lambda t: t["estimated_value"] is not None and t["estimated_value"] <= 100000
    )


@pytest.mark.parametrize("status", ["none", "to_review", "verified"])
def test_filter_report_status(client: TestClient, everything: list[dict], status: str) -> None:
    body = _get(client, report_status=status, include_discarded=True, page_size=100)
    expected = _expected_ids(everything, lambda t: t["report_status"] == status)
    assert set(_ids(body)) == expected
    assert expected


def test_filter_text_search(client: TestClient, everything: list[dict]) -> None:
    word = "CLOUD"
    body = _get(client, q=word, include_discarded=True, page_size=100)

    def matches(t: dict) -> bool:
        haystack = " ".join([t["title"], t["description"] or "", t["buyer_name"]]).lower()
        return word.lower() in haystack

    expected = _expected_ids(everything, matches)
    assert set(_ids(body)) == expected
    assert expected
    assert _get(client, q="zzz-nessun-risultato")["total"] == 0


def test_filters_are_combined_with_and(client: TestClient, everything: list[dict]) -> None:
    body = _get(client, min_score=3, cpv="72", report_status="none", page_size=100)
    expected = _expected_ids(
        everything,
        lambda t: (
            t["discard_reason"] is None
            and t["relevance_score"] >= 3
            and any(c.startswith("72") for c in t["cpv_codes"])
            and t["report_status"] == "none"
        ),
    )
    assert set(_ids(body)) == expected


def test_sort_relevance_is_default(client: TestClient) -> None:
    body = _get(client, include_discarded=True, page_size=100)
    assert _ids(body) == _ids(_get(client, sort="relevance", include_discarded=True, page_size=100))
    keys = [
        (
            -t["relevance_score"],
            t["submission_deadline"] is None,
            _utc(t["submission_deadline"]),
        )
        for t in body["items"]
    ]
    assert keys == sorted(keys)


def _utc(value: str | None) -> float:
    return datetime.fromisoformat(value).timestamp() if value else 0.0


def test_sort_deadline_puts_tenders_without_deadline_last(client: TestClient) -> None:
    items = _get(client, sort="deadline", include_discarded=True, page_size=100)["items"]
    with_deadline = [t for t in items if t["submission_deadline"]]
    assert items[: len(with_deadline)] == with_deadline
    stamps = [_utc(t["submission_deadline"]) for t in with_deadline]
    assert stamps == sorted(stamps)
    assert len(with_deadline) < len(items)


def test_sort_published_is_descending(client: TestClient) -> None:
    items = _get(client, sort="published", include_discarded=True, page_size=100)["items"]
    dates = [t["publication_date"] for t in items]
    assert dates == sorted(dates, reverse=True)


def test_pagination(client: TestClient) -> None:
    full = _get(client, include_discarded=True, page_size=100)
    first = _get(client, include_discarded=True, page_size=7, page=1)
    third = _get(client, include_discarded=True, page_size=7, page=3)
    assert (first["total"], first["page"], first["page_size"]) == (20, 1, 7)
    assert _ids(first) == _ids(full)[:7]
    assert _ids(third) == _ids(full)[14:20]
    assert len(_ids(third)) == 6


def test_page_beyond_last_returns_empty_items_with_total(client: TestClient) -> None:
    body = _get(client, include_discarded=True, page_size=10, page=99)
    assert body["items"] == []
    assert (body["total"], body["page"], body["page_size"]) == (20, 99, 10)


def test_default_and_maximum_page_size(client: TestClient) -> None:
    assert len(_get(client, include_discarded=True)["items"]) == 20
    assert client.get("/tenders", params={"page_size": 101}).status_code == 422


def test_timestamps_have_timezone_and_deadline_is_in_rome(client: TestClient) -> None:
    for item in _get(client, include_discarded=True, page_size=100)["items"]:
        assert datetime.fromisoformat(item["created_at"]).utcoffset() is not None
        if item["submission_deadline"]:
            offset = datetime.fromisoformat(item["submission_deadline"]).utcoffset()
            assert offset is not None
            assert offset.total_seconds() in (3600, 7200)


@pytest.mark.parametrize(
    "params",
    [
        {"deadline_from": "2026-11-10", "deadline_to": "2026-11-01"},
        {"min_value": 10, "max_value": 5},
        {"report_status": "other"},
        {"sort": "unknown"},
        {"min_score": 0},
        {"page": 0},
    ],
)
def test_invalid_filters_return_422(client: TestClient, params: dict) -> None:
    response = client.get("/tenders", params=params)
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error", "message"}
    assert body["error"] == "validation_error"


def test_repository_invalid_query_error_is_mapped_to_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise InvalidQueryError("parametro non valido dal repository")

    monkeypatch.setattr(tenders_module.repository, "list_tenders", boom)
    response = client.get("/tenders")
    assert response.status_code == 422
    assert response.json() == {
        "error": "validation_error",
        "message": "parametro non valido dal repository",
    }


def test_other_value_error_is_not_a_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un ValueError che non è del dominio è un bug del server (500), non un errore del client."""

    def boom(*args: Any, **kwargs: Any) -> None:
        raise ValueError("errore interno qualsiasi")

    monkeypatch.setattr(tenders_module.repository, "list_tenders", boom)
    server_errors = TestClient(make_app(make_seeded_engine()), raise_server_exceptions=False)
    response = server_errors.get("/tenders")
    assert response.status_code == 500
    assert response.json() == {"error": "internal_error", "message": "Errore interno del server."}


def test_repository_inverted_ranges_message_comes_from_repository(client: TestClient) -> None:
    response = client.get("/tenders", params={"min_value": 10, "max_value": 5})
    assert "min_value" in response.json()["message"]
