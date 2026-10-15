"""Fixture condivise dai test."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from openapi_spec_validator.readers import read_from_filename

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "API_CONTRACT.yaml"


@pytest.fixture(scope="session")
def spec() -> dict:
    """Contratto API (docs/API_CONTRACT.yaml) letto come dizionario."""
    data, _ = read_from_filename(str(CONTRACT))
    return data


@pytest.fixture(autouse=True)
def _no_real_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """I test non toccano mai il database vero: `DATABASE_URL` dell'ambiente viene ignorata."""
    monkeypatch.delenv("DATABASE_URL", raising=False)


def pytest_configure(config: pytest.Config) -> None:
    """Registra i marker del progetto (pyproject.toml è condiviso e non si tocca)."""
    config.addinivalue_line(
        "markers", "contract: test di conformità dell'API a docs/API_CONTRACT.yaml (CI)"
    )
    config.addinivalue_line(
        "markers", "e2e: test end-to-end TED finto -> job -> database -> API (CI, nessuna rete)"
    )


@pytest.fixture(autouse=True)
def _join_manual_run_thread() -> Iterator[None]:
    """Attende il thread di `POST /runs` avviato da un test, così non invade il successivo."""
    yield
    from backend.api import runs

    thread = runs._job_thread
    if thread is not None:
        thread.join(timeout=10)
