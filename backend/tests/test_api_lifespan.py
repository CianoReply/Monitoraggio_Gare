"""Test del ciclo di vita dell'app (T4.1): log JSON e scheduler opzionale. Senza rete."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api import main as main_module
from backend.api.main import create_app, scheduler_enabled


class FakeScheduler:
    def __init__(self) -> None:
        self.shutdown_calls: list[bool] = []

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


@pytest.fixture
def hooks(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Sostituisce configure_logging e start_scheduler con finti che registrano le chiamate."""
    state: dict[str, Any] = {"logging": 0, "started": 0, "scheduler": FakeScheduler()}

    def fake_configure_logging(*args: Any, **kwargs: Any) -> None:
        state["logging"] += 1

    def fake_start_scheduler() -> FakeScheduler:
        state["started"] += 1
        return state["scheduler"]

    monkeypatch.setattr(main_module, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(main_module, "start_scheduler", fake_start_scheduler)
    return state


def test_scheduler_is_off_without_the_variable(
    monkeypatch: pytest.MonkeyPatch, hooks: dict[str, Any]
) -> None:
    monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert hooks["started"] == 0
    assert hooks["started"] == 0
    assert hooks["scheduler"].shutdown_calls == []
    assert hooks["logging"] == 1  # il log JSON si configura sempre


@pytest.mark.parametrize("value", ["", "false", "0", "yes", "tru", "1"])
def test_scheduler_is_off_for_any_value_other_than_true(
    monkeypatch: pytest.MonkeyPatch, hooks: dict[str, Any], value: str
) -> None:
    monkeypatch.setenv("ENABLE_SCHEDULER", value)
    with TestClient(create_app()):
        pass
    assert hooks["started"] == 0


@pytest.mark.parametrize("value", ["true", "TRUE", " True "])
def test_scheduler_starts_with_true_and_stops_on_shutdown(
    monkeypatch: pytest.MonkeyPatch, hooks: dict[str, Any], value: str
) -> None:
    monkeypatch.setenv("ENABLE_SCHEDULER", value)
    with TestClient(create_app()) as client:
        assert hooks["started"] == 1
        assert hooks["scheduler"].shutdown_calls == []  # ancora attivo mentre l'app serve
        assert client.get("/health").status_code == 200
    assert hooks["started"] == 1
    assert hooks["scheduler"].shutdown_calls == [False]  # shutdown(wait=False) alla chiusura


def test_scheduler_is_stopped_even_if_the_app_fails(
    monkeypatch: pytest.MonkeyPatch, hooks: dict[str, Any]
) -> None:
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")
    with pytest.raises(RuntimeError, match="boom"), TestClient(create_app()):
        raise RuntimeError("boom")
    assert hooks["scheduler"].shutdown_calls == [False]


def test_logging_is_configured_once_per_startup(hooks: dict[str, Any]) -> None:
    with TestClient(create_app()):
        pass
    with TestClient(create_app()):
        pass
    assert hooks["logging"] == 2


def test_plain_test_client_does_not_start_lifespan(hooks: dict[str, Any]) -> None:
    # Senza `with` Starlette non esegue il ciclo di vita: i test normali non toccano scheduler/log.
    assert TestClient(create_app()).get("/health").status_code == 200
    assert hooks["logging"] == 0
    assert hooks["started"] == 0


@pytest.mark.parametrize(
    ("value", "expected"), [(None, False), ("true", True), ("True", True), ("false", False)]
)
def test_scheduler_enabled_helper(
    monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool
) -> None:
    if value is None:
        monkeypatch.delenv("ENABLE_SCHEDULER", raising=False)
    else:
        monkeypatch.setenv("ENABLE_SCHEDULER", value)
    assert scheduler_enabled() is expected


def test_real_start_scheduler_is_called_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Senza finti sul modulo: `main` usa davvero `backend.ingestion.scheduler.start_scheduler`."""
    from backend.ingestion import logging_config, scheduler

    assert main_module.start_scheduler is scheduler.start_scheduler
    assert main_module.configure_logging is logging_config.configure_logging
