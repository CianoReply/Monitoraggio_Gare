"""Fixture condivise dai test."""

from pathlib import Path

import pytest
from openapi_spec_validator.readers import read_from_filename

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "API_CONTRACT.yaml"


@pytest.fixture(scope="session")
def spec() -> dict:
    """Contratto API (docs/API_CONTRACT.yaml) letto come dizionario."""
    data, _ = read_from_filename(str(CONTRACT))
    return data


def pytest_configure(config: pytest.Config) -> None:
    """Registra i marker del progetto (pyproject.toml è condiviso e non si tocca)."""
    config.addinivalue_line(
        "markers", "contract: test di conformità dell'API a docs/API_CONTRACT.yaml (CI)"
    )
