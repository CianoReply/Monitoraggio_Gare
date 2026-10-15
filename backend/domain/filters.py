"""Filtri automatici (passo 4): una funzione per regola, esito "tenuta" o "scartata con motivo".

Ogni regola riceve la gara (`TenderCreate`) e i parametri letti da `config.toml`; il motivo
dello scarto è il testo da salvare in `tenders.discard_reason`. I filtri su Paese e CPV
ripetono, come controllo di sicurezza, quelli già presenti nella query a TED (T1.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from backend.domain.config import FiltersConfig, load_filters_config
from backend.domain.schemas import TenderCreate

EURO = "EUR"


@dataclass(frozen=True)
class FilterResult:
    """Esito di una regola: `kept=True` oppure scartata con `reason`."""

    kept: bool
    reason: str | None = None

    @classmethod
    def keep(cls) -> FilterResult:
        return cls(True)

    @classmethod
    def discard(cls, reason: str) -> FilterResult:
        return cls(False, reason)


def filter_country(buyer_country: str | None, config: FiltersConfig | None = None) -> FilterResult:
    """Paese: l'ente appaltante deve essere in Italia.

    `TenderCreate` non ha un campo paese: lo passa il chiamante (parser, T1.3). Se non è
    noto (`None`) la gara è tenuta, perché la query a TED già filtra per paese.
    """
    config = config or load_filters_config()
    if buyer_country is None or buyer_country.strip().upper() in config.allowed_countries:
        return FilterResult.keep()
    return FilterResult.discard(f"Ente appaltante non italiano ({buyer_country.strip()})")


def filter_cpv(tender: TenderCreate, config: FiltersConfig | None = None) -> FilterResult:
    """Categoria IT: almeno un CPV deve iniziare con uno dei prefissi configurati."""
    config = config or load_filters_config()
    prefixes = tuple(config.cpv_prefixes)
    if any(code.startswith(prefixes) for code in tender.cpv_codes):
        return FilterResult.keep()
    return FilterResult.discard("Nessun CPV nella categoria IT")


def filter_notice_type(tender: TenderCreate, config: FiltersConfig | None = None) -> FilterResult:
    """Tipo di avviso: bando o preinformazione, non aggiudicazione.

    Una rettifica (con `parent_publication_number`) passa: la gestisce la deduplica (T1.4).
    """
    config = config or load_filters_config()
    if tender.parent_publication_number:
        return FilterResult.keep()
    notice_type = tender.notice_type.strip().lower()
    if any(term in notice_type for term in config.rejected_notice_type_terms):
        return FilterResult.discard(f"Tipo di avviso non ammesso ({tender.notice_type})")
    if any(term in notice_type for term in config.accepted_notice_type_terms):
        return FilterResult.keep()
    return FilterResult.discard(f"Tipo di avviso non ammesso ({tender.notice_type})")


def filter_deadline(tender: TenderCreate, now: datetime | None = None) -> FilterResult:
    """Scadenza: l'offerta si può ancora presentare (scadenza futura o assente)."""
    now = now or datetime.now(UTC)
    if tender.submission_deadline is None or tender.submission_deadline > now:
        return FilterResult.keep()
    return FilterResult.discard("Scadenza offerte già passata")


def filter_min_value(tender: TenderCreate, config: FiltersConfig | None = None) -> FilterResult:
    """Importo minimo: importo >= soglia (in euro) oppure importo assente.

    Un importo in valuta diversa dall'euro non si confronta (nessun cambio): la gara è tenuta.
    """
    config = config or load_filters_config()
    value: Decimal | None = tender.estimated_value
    if value is None or (tender.currency or EURO) != EURO or value >= config.min_value_eur:
        return FilterResult.keep()
    return FilterResult.discard(
        f"Importo {value:,.2f} EUR sotto la soglia di {config.min_value_eur:,.2f} EUR"
    )


def apply_filters(
    tender: TenderCreate,
    *,
    buyer_country: str | None = None,
    config: FiltersConfig | None = None,
    now: datetime | None = None,
) -> FilterResult:
    """Applica tutte le regole nell'ordine Paese, CPV, tipo, scadenza, importo.

    Restituisce l'esito della prima regola che scarta, altrimenti "tenuta".
    """
    config = config or load_filters_config()
    results = (
        filter_country(buyer_country, config),
        filter_cpv(tender, config),
        filter_notice_type(tender, config),
        filter_deadline(tender, now),
        filter_min_value(tender, config),
    )
    return next((r for r in results if not r.kept), FilterResult.keep())
