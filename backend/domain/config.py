"""Lettura della configurazione di dominio (`config.toml`): soglie, CPV, tipi di avviso."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.toml")


class ConfigError(ValueError):
    """Il file di configurazione manca di una voce o contiene un valore non valido."""


@dataclass(frozen=True)
class FiltersConfig:
    """Parametri dei filtri automatici (T2.2)."""

    min_value_eur: Decimal
    cpv_prefixes: tuple[str, ...]
    allowed_countries: tuple[str, ...]
    accepted_notice_type_terms: tuple[str, ...]
    rejected_notice_type_terms: tuple[str, ...]


def load_raw_config(path: Path | None = None) -> dict[str, Any]:
    """Legge il file TOML; senza argomenti usa `backend/domain/config.toml`."""
    with open(path or DEFAULT_CONFIG_PATH, "rb") as handle:
        return tomllib.load(handle)


def _string_list(section: dict[str, Any], key: str, *, lower: bool = False) -> tuple[str, ...]:
    values = section.get(key)
    required = key != "rejected_notice_type_terms"
    if (
        not isinstance(values, list)
        or (required and not values)
        or not all(isinstance(v, str) and v for v in values)
    ):
        raise ConfigError(f"filters.{key} deve essere una lista di stringhe non vuote")
    return tuple(v.lower() if lower else v for v in values)


def load_filters_config(path: Path | None = None) -> FiltersConfig:
    """Carica e valida la sezione `[filters]`."""
    section = load_raw_config(path).get("filters")
    if not isinstance(section, dict):
        raise ConfigError("manca la sezione [filters]")
    value = section.get("min_value_eur")
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ConfigError("filters.min_value_eur deve essere un numero >= 0")
    cpv_prefixes = _string_list(section, "cpv_prefixes")
    if not all(p.isdigit() and 2 <= len(p) <= 8 for p in cpv_prefixes):
        raise ConfigError("filters.cpv_prefixes: servono prefissi di 2-8 cifre")
    return FiltersConfig(
        min_value_eur=Decimal(str(value)),
        cpv_prefixes=cpv_prefixes,
        allowed_countries=tuple(c.upper() for c in _string_list(section, "allowed_countries")),
        accepted_notice_type_terms=_string_list(section, "accepted_notice_type_terms", lower=True),
        rejected_notice_type_terms=_string_list(section, "rejected_notice_type_terms", lower=True),
    )
