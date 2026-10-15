"""Punteggio di pertinenza 1-5 con regole deterministiche e trasparenti (nessun LLM).

Regole (pesi e parole chiave in `config.toml`, sezione `[scoring]`; ADR-005, ADR-010):

| Criterio                                              | Punti (predefiniti)      |
|-------------------------------------------------------|--------------------------|
| Almeno un CPV "core"                                  | +2                       |
| Altrimenti almeno un altro CPV IT                     | +1                       |
| Parole chiave nel titolo o nella descrizione          | +1 ogni 2 trovate, max +2|
| Importo >= 1.000.000 EUR (o senza valuta)             | +1                       |
| Scadenza tra 10 e 60 giorni                           | +1                       |
| Scadenza a meno di 5 giorni (o già passata)           | -1                       |

Il totale diventa il voto: <= 1 -> 1, 2 -> 2, 3 -> 3, 4 -> 4, >= 5 -> 5.
Il punteggio si calcola per OGNI gara, anche se scartata dai filtri (ADR-010).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.domain.config import ScoringConfig
from backend.domain.filters import EURO, FilterResult
from backend.domain.schemas import TenderCreate, TenderEvaluation

SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class ScoreComponent:
    """Un criterio che ha contribuito al totale, con il motivo leggibile."""

    rule: str
    points: int
    detail: str


@dataclass(frozen=True)
class ScoreBreakdown:
    """Totale grezzo, voto 1-5 e criteri applicati (serve a spiegare il voto)."""

    components: tuple[ScoreComponent, ...]

    @property
    def total(self) -> int:
        return sum(c.points for c in self.components)

    @property
    def score(self) -> int:
        return total_to_score(self.total)


def total_to_score(total: int) -> int:
    """Converte il totale dei punti in un voto da 1 a 5."""
    return max(1, min(5, total))


def _matched_keywords(tender: TenderCreate, config: ScoringConfig) -> list[str]:
    """Parole chiave (distinte, parola intera) presenti in titolo o descrizione."""
    text = html.unescape(f"{tender.title} {tender.description or ''}").lower()
    found = []
    for keyword in dict.fromkeys(config.keywords):
        if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text):
            found.append(keyword)
    return found


def score_breakdown(
    tender: TenderCreate, config: ScoringConfig, now: datetime | None = None
) -> ScoreBreakdown:
    """Calcola i criteri applicati alla gara. `now` (con fuso) serve per la scadenza."""
    if now is None:
        now = datetime.now(UTC)
    elif now.tzinfo is None:
        raise ValueError("now deve avere il fuso orario (datetime aware)")
    components: list[ScoreComponent] = []

    core = [c for c in tender.cpv_codes if c.startswith(config.core_cpv_prefixes)]
    other = [c for c in tender.cpv_codes if c.startswith(config.it_cpv_prefixes)]
    if core:
        components.append(ScoreComponent("cpv", config.core_cpv_points, f"CPV core {core[0]}"))
    elif other:
        components.append(ScoreComponent("cpv", config.other_cpv_points, f"CPV IT {other[0]}"))

    keywords = _matched_keywords(tender, config)
    keyword_points = min(len(keywords) // config.keyword_words_per_point, config.keyword_max_points)
    if keyword_points:
        components.append(ScoreComponent("keywords", keyword_points, ", ".join(keywords)))

    value = tender.estimated_value
    if value is not None and (tender.currency or EURO) == EURO and value >= config.high_value_eur:
        components.append(
            ScoreComponent("value", config.high_value_points, f"importo {value:,.2f} EUR")
        )

    if tender.submission_deadline is not None:
        days = (tender.submission_deadline - now).total_seconds() / SECONDS_PER_DAY
        if config.deadline_ok_min_days <= days <= config.deadline_ok_max_days:
            components.append(
                ScoreComponent(
                    "deadline", config.deadline_ok_points, f"scadenza tra {days:.0f} giorni"
                )
            )
        elif days < config.deadline_urgent_days:
            components.append(
                ScoreComponent(
                    "deadline", config.deadline_urgent_points, f"scadenza tra {days:.0f} giorni"
                )
            )
    return ScoreBreakdown(tuple(components))


def compute_score(tender: TenderCreate, config: ScoringConfig, now: datetime | None = None) -> int:
    """Voto di pertinenza da 1 a 5 della gara."""
    return score_breakdown(tender, config, now).score


def evaluate_tender(
    tender: TenderCreate,
    filter_result: FilterResult,
    config: ScoringConfig,
    now: datetime | None = None,
) -> TenderEvaluation:
    """Esito completo, pronto per `repository.upsert_tender` (usato dal job, T1.5).

    Il voto si calcola sempre (ADR-010). `is_relevant` è vero solo se la gara è tenuta dai
    filtri e il voto è >= `relevance_threshold`; `discard_reason` è il motivo dello scarto.
    """
    score = compute_score(tender, config, now)
    return TenderEvaluation(
        relevance_score=score,
        is_relevant=filter_result.kept and score >= config.relevance_threshold,
        discard_reason=None if filter_result.kept else filter_result.reason,
    )
