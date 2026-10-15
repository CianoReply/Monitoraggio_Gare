"""Aiuti per i test di punteggio: scrittura di file `config.toml` con sezione `[scoring]`."""

from collections.abc import Callable
from pathlib import Path

from backend.domain.config import ScoringConfig, load_scoring_config

# Valori validi minimi; i test li sovrascrivono uno per volta.
BASE_SCORING = {
    "relevance_threshold": "3",
    "core_cpv_prefixes": '["722", "725"]',
    "core_cpv_points": "2",
    "it_cpv_prefixes": '["72", "48"]',
    "other_cpv_points": "1",
    "keywords": '["cloud"]',
    "keyword_words_per_point": "2",
    "keyword_max_points": "2",
    "high_value_eur": "1000000",
    "high_value_points": "1",
    "deadline_ok_min_days": "10",
    "deadline_ok_max_days": "60",
    "deadline_ok_points": "1",
    "deadline_urgent_days": "5",
    "deadline_urgent_points": "-1",
}

# Parole chiave usate dai test sulle regole di corrispondenza.
TEST_KEYWORDS = (
    '["cloud", "cybersecurity", "portale|portali", "applicativo|applicativi", '
    '"piattaforma|piattaforme", "datacenter|data center", "sviluppo software", "software"]'
)

ConfigFactory = Callable[..., ScoringConfig]


def write_scoring_path(tmp_path: Path, **overrides: str) -> Path:
    """Scrive un config.toml con la sola sezione [scoring] e ne restituisce il percorso."""
    values = {**BASE_SCORING, "keywords": TEST_KEYWORDS, **overrides}
    body = "\n".join(f"{k} = {v}" for k, v in values.items())
    path = tmp_path / "config.toml"
    path.write_text(f"[scoring]\n{body}\n", encoding="utf-8")
    return path


def make_scoring_factory(tmp_path: Path) -> ConfigFactory:
    def make(**overrides: str) -> ScoringConfig:
        return load_scoring_config(write_scoring_path(tmp_path, **overrides))

    return make
