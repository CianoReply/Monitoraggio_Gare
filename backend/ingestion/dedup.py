"""Deduplica e gestione delle rettifiche (T1.4, ADR-014).

Regole (docs/TED_API_NOTES.md, domanda 9):
- un avviso già salvato (stesso `publication_number`) viene aggiornato, mai duplicato;
- una rettifica (change notice) aggiorna la gara che modifica: si risale la catena
  `change-notice-version-identifier` → `notice-identifier` e si aggiorna il primo avviso della
  catena già presente nel database (di solito l'originale). La gara aggiornata mantiene il
  `publication_number`, la data di pubblicazione e `parent_publication_number` della riga;
  gli altri campi (scadenza, importo, `ted_url` della rettifica...) e `raw_data` prendono i valori
  della rettifica. Se la gara ha un report, torna `to_review`;
- un avviso più vecchio di quello già applicato alla riga (data di pubblicazione, poi numero)
  non la sovrascrive mai: l'ordine di arrivo da TED non è garantito;
- se nessun avviso della catena è nel database, la rettifica si salva come gara a sé, con
  `parent_publication_number` = avviso più lontano raggiunto nella catena (l'originale se la
  catena è completa) e un warning;
- se il lookup su TED fallisce, `save_notice` solleva `ChainLookupError` senza scrivere nulla:
  il chiamante salta l'avviso e lo riprova alla prossima esecuzione.
Limite noto: senza l'originale nel database possono restare due righe per la stessa gara
(originale arrivato dopo una rettifica salvata a sé, o due rettifiche salvate a sé in ordine
inverso).
Reimportare la stessa rettifica aggiorna la riga ma non riporta il report a `to_review`.
Il salvataggio passa sempre da `backend.domain.repository`.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.domain import repository
from backend.domain.models import Tender
from backend.domain.schemas import TenderCreate, TenderEvaluation
from backend.ingestion.parser import change_reference, first_value, parse_ted_date

logger = logging.getLogger(__name__)

# Dato un notice-identifier, restituisce l'avviso TED grezzo (almeno `publication-number`,
# `notice-identifier`, `change-notice-version-identifier`) oppure None se TED non lo trova.
NoticeLookup = Callable[[str], dict[str, Any] | None]
MAX_CHAIN_DEPTH = 20
LOOKUP_FIELDS = (
    "publication-number",
    "publication-date",
    "notice-identifier",
    "change-notice-version-identifier",
)
_PUBLICATION_NUMBER = re.compile(r"^(\d+)-(\d{4})$")


class ChainLookupError(Exception):
    """La ricerca su TED di un avviso della catena è fallita (rete, errore del server...)."""


@dataclass(frozen=True)
class ChainLink:
    """Un avviso della catena di modifiche: numero di pubblicazione e identificativo TED."""

    publication_number: str
    notice_identifier: str | None


@dataclass(frozen=True)
class Chain:
    """Avvisi modificati, dal più recente al più lontano; `complete` se arriva all'originale."""

    links: list[ChainLink]
    complete: bool


@dataclass(frozen=True)
class SaveOutcome:
    """Esito del salvataggio di un avviso."""

    tender: Tender
    created: bool
    is_change: bool
    report_reset: bool = False
    original_publication_number: str | None = None
    chain_complete: bool = True
    skipped_as_older: bool = False


def notice_order_key(raw: dict[str, Any]) -> tuple[str, int, int]:
    """Chiave per ordinare gli avvisi nel tempo: data di pubblicazione, anno e numero.

    I numeri di pubblicazione TED crescono nel corso dell'anno (es. 566426-2026 < 687833-2026).
    Una data mancante vale come la più vecchia; un numero non standard vale (0, 0).
    """
    day = parse_ted_date(raw.get("publication-date"))
    number = first_value(raw.get("publication-number"))
    match = _PUBLICATION_NUMBER.match(number) if isinstance(number, str) else None
    year, serial = (int(match.group(2)), int(match.group(1))) if match else (0, 0)
    return (day.isoformat() if day else "", year, serial)


def resolve_chain(
    raw: dict[str, Any],
    lookup: NoticeLookup,
    is_saved: Callable[[str], bool] | None = None,
) -> Chain:
    """Risale gli avvisi modificati da `raw` (catena vuota e completa se non è una rettifica).

    Si ferma al primo avviso per cui `is_saved(publication_number)` è vero (nessuna chiamata
    TED in più), se TED non trova un avviso (catena incompleta), se la catena ha un ciclo o supera
    `MAX_CHAIN_DEPTH`. Un'eccezione del lookup diventa `ChainLookupError`.
    """
    links: list[ChainLink] = []
    seen: set[str] = set()
    reference = change_reference(raw)
    while reference is not None:
        if reference in seen or len(links) >= MAX_CHAIN_DEPTH:
            logger.warning("Catena di rettifiche interrotta (ciclo o troppo lunga): %s", reference)
            return Chain(links, complete=False)
        seen.add(reference)
        try:
            predecessor = lookup(reference)
        except Exception as exc:
            raise ChainLookupError(
                f"Ricerca su TED fallita per {reference}: {exc.__class__.__name__}: {exc}"
            ) from exc
        number = first_value(predecessor.get("publication-number")) if predecessor else None
        if not isinstance(number, str) or not number:
            logger.warning("Avviso modificato non trovato su TED: notice-identifier %s", reference)
            return Chain(links, complete=False)
        links.append(ChainLink(number, reference))
        if is_saved is not None and is_saved(number):
            return Chain(links, complete=True)
        reference = change_reference(predecessor) if predecessor else None
    return Chain(links, complete=True)


class TedNoticeLookup:
    """`NoticeLookup` basato su un client TED, con cache per la durata di un'esecuzione."""

    def __init__(self, search: Callable[..., list[dict[str, Any]]]) -> None:
        self._search = search
        self._cache: dict[str, dict[str, Any] | None] = {}

    def __call__(self, notice_identifier: str) -> dict[str, Any] | None:
        if notice_identifier not in self._cache:
            notices = self._search(f"notice-identifier={notice_identifier}", LOOKUP_FIELDS)
            self._cache[notice_identifier] = notices[0] if notices else None
        return self._cache[notice_identifier]


def _is_older_than_saved(raw: dict[str, Any], saved: Tender) -> bool:
    return notice_order_key(raw) < notice_order_key(saved.raw_data or {})


def save_notice(
    session: Session,
    tender: TenderCreate,
    evaluation: TenderEvaluation,
    lookup: NoticeLookup,
) -> SaveOutcome:
    """Salva un avviso già convertito e valutato, gestendo duplicati, rettifiche e ordine."""
    raw = tender.raw_data
    if not change_reference(raw):
        existing = repository.get_tender_by_publication_number(session, tender.publication_number)
        if existing is not None and _is_older_than_saved(raw, existing):
            logger.info(
                "Avviso %s già aggiornato da un avviso più recente", tender.publication_number
            )
            return SaveOutcome(existing, created=False, is_change=False, skipped_as_older=True)
        result = repository.upsert_tender(session, tender, evaluation)
        return SaveOutcome(result.tender, result.created, is_change=False)

    def is_saved(publication_number: str) -> bool:
        return repository.get_tender_by_publication_number(session, publication_number) is not None

    chain = resolve_chain(raw, lookup, is_saved)
    for link in chain.links:
        target = repository.get_tender_by_publication_number(session, link.publication_number)
        if target is None:
            continue
        if _is_older_than_saved(raw, target):
            logger.info(
                "Rettifica %s più vecchia di quella già applicata alla gara %s: ignorata",
                tender.publication_number,
                target.publication_number,
            )
            return SaveOutcome(
                target,
                created=False,
                is_change=True,
                original_publication_number=target.publication_number,
                chain_complete=chain.complete,
                skipped_as_older=True,
            )
        merged = tender.model_copy(
            update={
                "publication_number": target.publication_number,
                "publication_date": target.publication_date,
                "parent_publication_number": target.parent_publication_number,
            }
        )
        already_applied = (target.raw_data or {}).get("publication-number") == raw.get(
            "publication-number"
        )
        result = repository.upsert_tender(session, merged, evaluation)
        # La stessa rettifica reimportata non cambia i dati: il report verificato resta tale.
        reset = (
            False if already_applied else repository.reset_report_to_review(session, result.tender)
        )
        logger.info(
            "Rettifica %s applicata alla gara %s%s",
            tender.publication_number,
            target.publication_number,
            " (report riportato a to_review)" if reset else "",
        )
        return SaveOutcome(
            result.tender,
            created=False,
            is_change=True,
            report_reset=reset,
            original_publication_number=target.publication_number,
            chain_complete=chain.complete,
        )

    farthest = chain.links[-1].publication_number if chain.links else None
    if farthest is not None and not _PUBLICATION_NUMBER.match(farthest):
        logger.warning("Numero di pubblicazione dell'originale non valido: %r", farthest[:60])
        farthest = None
    logger.warning(
        "Rettifica %s senza gara originale nel database (avviso più lontano su TED: %s%s): "
        "salvata a sé",
        tender.publication_number,
        farthest or "nessuno",
        "" if chain.complete else ", catena incompleta",
    )
    standalone = tender.model_copy(update={"parent_publication_number": farthest})
    result = repository.upsert_tender(session, standalone, evaluation)
    return SaveOutcome(
        result.tender,
        result.created,
        is_change=True,
        original_publication_number=farthest,
        chain_complete=chain.complete,
    )
