"""Deduplica e gestione delle rettifiche (T1.4).

Regole (docs/TED_API_NOTES.md, domanda 9):
- un avviso già salvato (stesso `publication_number`) viene aggiornato, mai duplicato;
- una rettifica (change notice) aggiorna la gara che modifica: si risale la catena
  `change-notice-version-identifier` → `notice-identifier` e si aggiorna il primo avviso della
  catena già presente nel database (di solito l'originale). La gara aggiornata mantiene il
  `publication_number` e la data di pubblicazione dell'originale; gli altri campi (es. la scadenza)
  e `raw_data` prendono i valori della rettifica. Se la gara ha un report, torna `to_review`;
- se nessun avviso della catena è nel database, la rettifica si salva come gara a sé, con
  `parent_publication_number` = numero dell'avviso originale (se TED lo restituisce), e un warning.
Il salvataggio passa sempre da `backend.domain.repository`.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.domain import repository
from backend.domain.models import Tender
from backend.domain.schemas import TenderCreate, TenderEvaluation
from backend.ingestion.parser import change_reference, first_value

logger = logging.getLogger(__name__)

# Dato un notice-identifier, restituisce l'avviso TED grezzo (almeno `publication-number`,
# `notice-identifier`, `change-notice-version-identifier`) oppure None se TED non lo trova.
NoticeLookup = Callable[[str], dict[str, Any] | None]
MAX_CHAIN_DEPTH = 20
LOOKUP_FIELDS = ("publication-number", "notice-identifier", "change-notice-version-identifier")


@dataclass(frozen=True)
class ChainLink:
    """Un avviso della catena di modifiche: numero di pubblicazione e identificativo TED."""

    publication_number: str
    notice_identifier: str | None


@dataclass(frozen=True)
class SaveOutcome:
    """Esito del salvataggio di un avviso."""

    tender: Tender
    created: bool
    is_change: bool
    report_reset: bool = False
    original_publication_number: str | None = None


def resolve_chain(raw: dict[str, Any], lookup: NoticeLookup) -> list[ChainLink]:
    """Avvisi modificati da `raw`, dal più recente all'originale (vuota se non è una rettifica).

    Si ferma se TED non trova un avviso, se la catena ha un ciclo o supera `MAX_CHAIN_DEPTH`.
    """
    chain: list[ChainLink] = []
    seen: set[str] = set()
    reference = change_reference(raw)
    while reference is not None and reference not in seen and len(chain) < MAX_CHAIN_DEPTH:
        seen.add(reference)
        predecessor = lookup(reference)
        if predecessor is None:
            logger.warning("Avviso modificato non trovato su TED: notice-identifier %s", reference)
            break
        number = first_value(predecessor.get("publication-number"))
        if not isinstance(number, str) or not number:
            break
        chain.append(ChainLink(number, reference))
        reference = change_reference(predecessor)
    return chain


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


def save_notice(
    session: Session,
    tender: TenderCreate,
    evaluation: TenderEvaluation,
    lookup: NoticeLookup,
) -> SaveOutcome:
    """Salva un avviso già convertito e valutato, gestendo duplicati e rettifiche."""
    raw = tender.raw_data
    if not change_reference(raw):
        existing = repository.get_tender_by_publication_number(session, tender.publication_number)
        if existing is not None and change_reference(existing.raw_data or {}):
            # La gara contiene già i dati di una rettifica successiva: reimportare l'avviso
            # originale (es. una seconda esecuzione dello stesso giorno) non deve annullarla.
            logger.info(
                "Avviso %s già aggiornato da una rettifica: non sovrascritto",
                tender.publication_number,
            )
            return SaveOutcome(existing, created=False, is_change=False)
        result = repository.upsert_tender(session, tender, evaluation)
        return SaveOutcome(result.tender, result.created, is_change=False)

    chain = resolve_chain(raw, lookup)
    for link in chain:
        target = repository.get_tender_by_publication_number(session, link.publication_number)
        if target is not None:
            merged = tender.model_copy(
                update={
                    "publication_number": target.publication_number,
                    "publication_date": target.publication_date,
                    "parent_publication_number": target.parent_publication_number,
                }
            )
            result = repository.upsert_tender(session, merged, evaluation)
            reset = repository.reset_report_to_review(session, result.tender)
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
            )

    original = chain[-1].publication_number if chain else None
    logger.warning(
        "Rettifica %s senza gara originale nel database (originale TED: %s): salvata a sé",
        tender.publication_number,
        original or "non trovato",
    )
    standalone = tender.model_copy(update={"parent_publication_number": original})
    result = repository.upsert_tender(session, standalone, evaluation)
    return SaveOutcome(
        result.tender,
        result.created,
        is_change=True,
        original_publication_number=original,
    )
