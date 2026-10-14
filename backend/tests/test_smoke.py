"""Test di fumo: verifica che i pacchetti del backend siano importabili.

Serve anche a far uscire pytest con codice 0 finché non esistono test reali
(senza test pytest esce con codice 5, che la CI considera un errore).
"""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    ["backend.ingestion", "backend.domain", "backend.api"],
)
def test_module_is_importable(module_name: str) -> None:
    assert importlib.import_module(module_name) is not None
