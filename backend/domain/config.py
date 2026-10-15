"""Lettura della configurazione di dominio (`config.toml`): filtri e punteggio.

Il file si legge una volta (all'avvio del job) e le configurazioni risultanti si passano
alle funzioni che le usano: nessuna cache globale.
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


@dataclass(frozen=True)
class ScoringConfig:
    """Parametri del punteggio di pertinenza (T2.3)."""

    relevance_threshold: int
    core_cpv_prefixes: tuple[str, ...]
    core_cpv_points: int
    it_cpv_prefixes: tuple[str, ...]
    other_cpv_points: int
    keywords: tuple[str, ...]
    keyword_words_per_point: int
    keyword_max_points: int
    high_value_eur: Decimal
    high_value_points: int
    deadline_ok_min_days: int
    deadline_ok_max_days: int
    deadline_ok_points: int
    deadline_urgent_days: int
    deadline_urgent_points: int


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


def _section(path: Path, name: str) -> dict[str, Any]:
    section = load_raw_config(path).get(name)
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: manca la sezione [{name}]")
    return section


def _string_list(
    section: dict[str, Any],
    key: str,
    where: str,
    *,
    lower: bool = False,
    upper: bool = False,
) -> tuple[str, ...]:
    """Lista non vuota di stringhe non vuote, normalizzata in minuscolo o maiuscolo."""
    values = section.get(key)
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(v, str) and v.strip() for v in values)
    ):
        raise ConfigError(f"{where}.{key} deve essere una lista non vuota di stringhe")
    cleaned = [v.strip() for v in values]
    if lower:
        cleaned = [v.lower() for v in cleaned]
    if upper:
        cleaned = [v.upper() for v in cleaned]
    return tuple(cleaned)


def _number(
    section: dict[str, Any], key: str, where: str, *, minimum: float | None = None
) -> int | float:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{where}.{key} deve essere un numero")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{where}.{key} deve essere >= {minimum}")
    return value


def _integer(section: dict[str, Any], key: str, where: str, *, minimum: int | None = None) -> int:
    value = section.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where}.{key} deve essere un intero")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{where}.{key} deve essere >= {minimum}")
    return value


def _cpv_prefixes(values: tuple[str, ...], where: str) -> tuple[str, ...]:
    if not all(p.isdigit() and 2 <= len(p) <= 8 for p in values):
        raise ConfigError(f"{where}: servono prefissi di 2-8 cifre")
    return values


def load_filters_config(path: Path | None = None) -> FiltersConfig:
    """Carica e valida la sezione `[filters]`."""
    path = path or DEFAULT_CONFIG_PATH
    section = _section(path, "filters")
    where = f"{path}: filters"
    value = section.get("min_value_eur")
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ConfigError(f"{path}: filters.min_value_eur deve essere un numero >= 0")
    return FiltersConfig(
        min_value_eur=Decimal(str(value)),
        cpv_prefixes=_cpv_prefixes(
            _string_list(section, "cpv_prefixes", where), f"{where}.cpv_prefixes"
        ),
        allowed_countries=_string_list(section, "allowed_countries", where, upper=True),
        accepted_notice_types=_string_list(section, "accepted_notice_types", where, lower=True),
    )


def load_scoring_config(path: Path | None = None) -> ScoringConfig:
    """Carica e valida la sezione `[scoring]`."""
    path = path or DEFAULT_CONFIG_PATH
    section = _section(path, "scoring")
    where = f"{path}: scoring"
    threshold = _integer(section, "relevance_threshold", where, minimum=1)
    if threshold > 5:
        raise ConfigError(f"{where}.relevance_threshold deve essere tra 1 e 5")
    ok_min = _integer(section, "deadline_ok_min_days", where, minimum=0)
    ok_max = _integer(section, "deadline_ok_max_days", where, minimum=0)
    if ok_min > ok_max:
        raise ConfigError(f"{where}: deadline_ok_min_days non può superare deadline_ok_max_days")
    urgent_days = _integer(section, "deadline_urgent_days", where, minimum=0)
    if urgent_days >= ok_min:
        raise ConfigError(f"{where}: deadline_urgent_days deve essere < deadline_ok_min_days")
    keywords = _string_list(section, "keywords", where, lower=True)
    if any(not [v for v in k.split("|") if v.strip()] for k in keywords):
        raise ConfigError(f'{where}.keywords: voce senza parole (solo "|")')
    return ScoringConfig(
        relevance_threshold=threshold,
        core_cpv_prefixes=_cpv_prefixes(
            _string_list(section, "core_cpv_prefixes", where), f"{where}.core_cpv_prefixes"
        ),
        core_cpv_points=_integer(section, "core_cpv_points", where),
        it_cpv_prefixes=_cpv_prefixes(
            _string_list(section, "it_cpv_prefixes", where), f"{where}.it_cpv_prefixes"
        ),
        other_cpv_points=_integer(section, "other_cpv_points", where),
        keywords=keywords,
        keyword_words_per_point=_integer(section, "keyword_words_per_point", where, minimum=1),
        keyword_max_points=_integer(section, "keyword_max_points", where, minimum=0),
        high_value_eur=Decimal(str(_number(section, "high_value_eur", where, minimum=0))),
        high_value_points=_integer(section, "high_value_points", where),
        deadline_ok_min_days=ok_min,
        deadline_ok_max_days=ok_max,
        deadline_ok_points=_integer(section, "deadline_ok_points", where),
        deadline_urgent_days=urgent_days,
        deadline_urgent_points=_integer(section, "deadline_urgent_points", where),
    )
