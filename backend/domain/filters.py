"""Filtri automatici (passo 4): una funzione per regola, esito "tenuta" o "scartata con motivo".

Ogni regola riceve la gara (`TenderCreate`) e i parametri letti da `config.toml`; il motivo
dello scarto è il testo da salvare in `tenders.discard_reason`. I filtri su Paese e CPV
ripetono, come controllo di sicurezza, quelli già presenti nella query a TED (T1.2).

La configurazione si carica una volta con `config.load_filters_config()` e si passa a
`apply_filters`: le funzioni non rileggono il file a ogni gara.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from backend.domain.config import FiltersConfig
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


def filter_country(
    buyer_country: str | Sequence[str] | None, config: FiltersConfig
) -> FilterResult:
    """Paese: l'ente appaltante deve essere in Italia (codici ISO a 3 lettere, es. "ITA").

    `buyer_country` è il valore di TED: un codice o la lista di codici degli enti. `TenderCreate`
    non ha un campo paese, quindi lo passa il chiamante. `None` significa "paese non noto":
    in quel caso la gara è TENUTA, perché la query a TED già filtra per paese. Con più enti
    basta che uno sia in un paese ammesso.
    """
    if buyer_country is None:
        return FilterResult.keep()
    countries = [buyer_country] if isinstance(buyer_country, str) else list(buyer_country)
    normalized = [c.strip().upper() for c in countries]
    if any(c in config.allowed_countries for c in normalized):
        return FilterResult.keep()
    return FilterResult.discard(f"Ente appaltante non italiano ({', '.join(normalized)})")


def filter_cpv(tender: TenderCreate, config: FiltersConfig) -> FilterResult:
    """Categoria IT: almeno un CPV deve iniziare con uno dei prefissi configurati."""
    if any(code.startswith(config.cpv_prefixes) for code in tender.cpv_codes):
        return FilterResult.keep()
    return FilterResult.discard("Nessun CPV nella categoria IT")


def filter_notice_type(tender: TenderCreate, config: FiltersConfig) -> FilterResult:
    """Tipo di avviso: solo i bandi (codici eForms `notice-type`, confronto esatto).

    Una rettifica ha lo stesso tipo dell'originale e si riconosce da `parent_publication_number`
    (valorizzato dal parser, T1.3): è tenuta, la gestisce la deduplica (T1.4).
    """
    if tender.parent_publication_number:
        return FilterResult.keep()
    notice_type = tender.notice_type.strip().lower()
    if notice_type in config.accepted_notice_types:
        return FilterResult.keep()
    if notice_type.startswith("can-") or notice_type in ("veat", "compl"):
        detail = "esito, non bando"
    elif notice_type.startswith("pin-"):
        detail = "preinformazione, non bando"
    else:
        detail = "non è un bando"
    return FilterResult.discard(f"Tipo di avviso {notice_type}: {detail}")


def filter_deadline(tender: TenderCreate, now: datetime | None = None) -> FilterResult:
    """Scadenza: l'offerta si può ancora presentare (scadenza futura o assente).

    `now` deve avere il fuso orario (ValueError se naive); senza `now` si usa l'ora corrente UTC.
    Il confronto è tra istanti, quindi indipendente dal fuso in cui sono espressi.
    """
    if now is None:
        now = datetime.now(UTC)
    elif now.tzinfo is None:
        raise ValueError("now deve avere il fuso orario (datetime aware)")
    if tender.submission_deadline is None or tender.submission_deadline > now:
        return FilterResult.keep()
    return FilterResult.discard("Scadenza offerte già passata")


def filter_min_value(tender: TenderCreate, config: FiltersConfig) -> FilterResult:
    """Importo minimo: importo >= soglia (in euro) oppure importo assente.

    Se `currency` è `None` l'importo è trattato come euro. Un importo in un'altra valuta non
    si confronta con la soglia (nessun cambio): la gara è tenuta.
    """
    value: Decimal | None = tender.estimated_value
    if value is None or (tender.currency or EURO) != EURO or value >= config.min_value_eur:
        return FilterResult.keep()
    return FilterResult.discard(
        f"Importo {value:,.2f} EUR sotto la soglia di {config.min_value_eur:,.2f} EUR"
    )


def apply_filters(
    tender: TenderCreate,
    *,
    buyer_country: str | Sequence[str] | None,
    config: FiltersConfig,
    now: datetime | None = None,
) -> FilterResult:
    """Applica le regole nell'ordine Paese, CPV, tipo, scadenza, importo.

    Restituisce l'esito della prima regola che scarta, altrimenti "tenuta". `buyer_country`
    è obbligatorio (vedi `filter_country`; `None` esplicito = non noto = tenuta). `config` si
    carica una sola volta con `load_filters_config()` e si riusa per tutte le gare.
    """
    rules = (
        lambda: filter_country(buyer_country, config),
        lambda: filter_cpv(tender, config),
        lambda: filter_notice_type(tender, config),
        lambda: filter_deadline(tender, now),
        lambda: filter_min_value(tender, config),
    )
    for rule in rules:
        result = rule()
        if not result.kept:
            return result
    return FilterResult.keep()
