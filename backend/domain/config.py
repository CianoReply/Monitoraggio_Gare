"""Lettura della configurazione di dominio (`config.toml`): soglie, CPV, tipi di avviso.

Il file si legge una volta (all'avvio del job) e la `FiltersConfig` risultante si passa
alle funzioni che la usano: nessuna cache globale.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.toml")


class ConfigError(ValueError):
    """Il file di configurazione manca, è malformato o contiene un valore non valido."""


@dataclass(frozen=True)
class FiltersConfig:
    """Parametri dei filtri automatici (T2.2)."""

    min_value_eur: Decimal
    cpv_prefixes: tuple[str, ...]
    allowed_countries: tuple[str, ...]
    accepted_notice_types: tuple[str, ...]


def load_raw_config(path: Path | None = None) -> dict[str, Any]:
    """Legge il file TOML; senza argomenti usa `backend/domain/config.toml`.

    Solleva `ConfigError` (con il percorso) se il file non si legge o non è TOML valido.
    """
    path = path or DEFAULT_CONFIG_PATH
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except OSError as exc:
        raise ConfigError(f"{path}: impossibile leggere il file ({exc})") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: TOML non valido ({exc})") from exc


def _string_list(
    section: dict[str, Any], key: str, path: Path, *, lower: bool = False, upper: bool = False
) -> tuple[str, ...]:
    """Lista non vuota di stringhe non vuote, normalizzata in minuscolo o maiuscolo."""
    values = section.get(key)
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(v, str) and v.strip() for v in values)
    ):
        raise ConfigError(f"{path}: filters.{key} deve essere una lista non vuota di stringhe")
    cleaned = [v.strip() for v in values]
    if lower:
        cleaned = [v.lower() for v in cleaned]
    if upper:
        cleaned = [v.upper() for v in cleaned]
    return tuple(cleaned)


def load_filters_config(path: Path | None = None) -> FiltersConfig:
    """Carica e valida la sezione `[filters]`."""
    path = path or DEFAULT_CONFIG_PATH
    section = load_raw_config(path).get("filters")
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: manca la sezione [filters]")
    value = section.get("min_value_eur")
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ConfigError(f"{path}: filters.min_value_eur deve essere un numero >= 0")
    cpv_prefixes = _string_list(section, "cpv_prefixes", path)
    if not all(p.isdigit() and 2 <= len(p) <= 8 for p in cpv_prefixes):
        raise ConfigError(f"{path}: filters.cpv_prefixes: servono prefissi di 2-8 cifre")
    return FiltersConfig(
        min_value_eur=Decimal(str(value)),
        cpv_prefixes=cpv_prefixes,
        allowed_countries=_string_list(section, "allowed_countries", path, upper=True),
        accepted_notice_types=_string_list(section, "accepted_notice_types", path, lower=True),
    )
