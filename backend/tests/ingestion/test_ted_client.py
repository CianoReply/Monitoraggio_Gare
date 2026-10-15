"""Test del client TED (T1.2): nessuna chiamata di rete, risposte da httpx.MockTransport."""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.ingestion import ted_client
from backend.ingestion.ted_client import (
    DEFAULT_API_URL,
    DEFAULT_CPV_PREFIXES,
    NOTICE_FIELDS,
    RETRY_DELAYS,
    TedApiError,
    TedClient,
    TedClientConfig,
    build_query,
    is_retryable_status,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
Handler = Callable[[httpx.Request], httpx.Response]


def daily_fixture() -> dict[str, Any]:
    data = json.loads((FIXTURES / "ted_search_it_2026-10-14.json").read_text(encoding="utf-8"))
    return data["response"]


class FakeClock:
    """Orologio finto: `sleep` fa avanzare il tempo e registra le attese."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


def make_client(handler: Handler, clock: FakeClock, **config: Any) -> TedClient:
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return TedClient(TedClientConfig(**config), http, sleep=clock.sleep, clock=clock.clock)


def test_build_query_uses_country_cpv_prefixes_and_day() -> None:
    query = build_query(date(2026, 10, 14), ("72", "48"))
    assert query == (
        "buyer-country=ITA AND classification-cpv IN (72* 48*) AND publication-date=20261014"
    )


@pytest.mark.parametrize(
    ("status", "expected"), [(200, False), (400, False), (404, False), (429, True), (500, True)]
)
def test_is_retryable_status(status: int, expected: bool) -> None:
    assert is_retryable_status(status) is expected


def test_config_defaults_respect_ted_limits() -> None:
    config = TedClientConfig()
    assert config.api_url == DEFAULT_API_URL
    assert len(NOTICE_FIELDS) * config.page_size <= 10_000


@pytest.mark.parametrize(
    "kwargs",
    [
        {"cpv_prefixes": ()},
        {"cpv_prefixes": ("72a",)},
        {"cpv_prefixes": ("123456789",)},
        {"page_size": 0},
        {"page_size": 251},
        {"page_size": 250},  # 41 campi × 250 supera 10.000
    ],
)
def test_config_rejects_invalid_values(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        TedClientConfig(**kwargs)


def test_config_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TED_API_URL", "https://example.invalid/search")
    monkeypatch.setenv("TED_CPV_PREFIXES", " 72, 48 ,,302 ")
    config = TedClientConfig.from_env()
    assert config.api_url == "https://example.invalid/search"
    assert config.cpv_prefixes == ("72", "48", "302")


def test_config_from_env_uses_defaults_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TED_API_URL", "")
    monkeypatch.delenv("TED_CPV_PREFIXES", raising=False)
    config = TedClientConfig.from_env()
    assert config.api_url == DEFAULT_API_URL
    assert config.cpv_prefixes == DEFAULT_CPV_PREFIXES


def test_fetch_notices_returns_fixture_notices_and_sends_expected_body() -> None:
    response = daily_fixture()
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={**response, "iterationNextToken": None})

    clock = FakeClock()
    notices = make_client(handler, clock).fetch_notices(date(2026, 10, 14))

    assert [n["publication-number"] for n in notices] == [
        n["publication-number"] for n in response["notices"]
    ]
    assert bodies == [
        {
            "query": build_query(date(2026, 10, 14), DEFAULT_CPV_PREFIXES),
            "fields": list(NOTICE_FIELDS),
            "limit": 200,
            "paginationMode": "ITERATION",
        }
    ]


def test_fetch_notices_follows_iteration_token_until_the_end() -> None:
    notices = daily_fixture()["notices"]
    pages = [
        {"notices": notices[:4], "iterationNextToken": "t1"},
        {"notices": notices[4:8], "iterationNextToken": "t2"},
        {"notices": notices[8:], "iterationNextToken": None},
    ]
    tokens: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        tokens.append(body.get("iterationNextToken"))
        return httpx.Response(200, json=pages[len(tokens) - 1])

    clock = FakeClock()
    result = make_client(handler, clock).fetch_notices(date(2026, 10, 14))

    assert len(result) == len(notices)
    assert tokens == [None, "t1", "t2"]
    # Pausa minima di 1 s tra le pagine (rate limit), nessuna prima della prima richiesta.
    assert clock.sleeps == [1.0, 1.0]


def test_search_stops_on_empty_page_even_with_token() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"notices": [], "iterationNextToken": "again"})

    assert make_client(handler, FakeClock()).search("q") == []
    assert calls == 1


def test_error_500_is_retried_three_times_then_fails() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="boom")

    clock = FakeClock()
    with pytest.raises(TedApiError, match="dopo 4 richieste"):
        make_client(handler, clock, min_interval=0).fetch_notices(date(2026, 10, 14))

    assert calls == 1 + 3  # prima richiesta + 3 tentativi
    assert clock.sleeps == list(RETRY_DELAYS) == [1.0, 2.0, 4.0]


def test_transient_errors_recover() -> None:
    responses: list[Any] = [
        httpx.ConnectError("rete giù"),
        httpx.Response(429, text="<html>429 Too Many Requests</html>"),
        httpx.Response(200, json={"notices": [{"publication-number": "1-2026"}]}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    clock = FakeClock()
    result = make_client(handler, clock, min_interval=0).search("q")

    assert result == [{"publication-number": "1-2026"}]
    assert clock.sleeps == [1.0, 2.0]


def test_client_error_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"message": "Value (251) of parameter 'limit'"})

    with pytest.raises(TedApiError, match="400"):
        make_client(handler, FakeClock()).search("q")
    assert calls == 1


def test_timeout_is_passed_to_each_request() -> None:
    seen: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return httpx.Response(200, json={"notices": []})

    make_client(handler, FakeClock()).search("q")
    assert seen == [{"connect": 30.0, "read": 30.0, "write": 30.0, "pool": 30.0}]


def test_client_context_manager_closes_http_client() -> None:
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with TedClient(TedClientConfig(), http):
        pass
    assert http.is_closed


def test_module_fetch_notices_uses_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class StubClient:
        def __init__(self, config: TedClientConfig | None) -> None:
            captured["config"] = config

        def __enter__(self) -> "StubClient":
            return self

        def __exit__(self, *exc_info: object) -> None:
            captured["closed"] = True

        def fetch_notices(self, publication_date: date) -> list[dict[str, Any]]:
            return [{"publication-number": publication_date.isoformat()}]

    monkeypatch.setattr(ted_client, "TedClient", StubClient)
    config = TedClientConfig()
    result = ted_client.fetch_notices(date(2026, 10, 14), config)
    assert result == [{"publication-number": "2026-10-14"}]
    assert captured == {"config": config, "closed": True}
