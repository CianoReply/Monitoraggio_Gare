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
