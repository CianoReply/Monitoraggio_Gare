"""Job giornaliero di raccolta (T1.5): TED → parser → filtri e punteggio → salvataggio → documenti.

`run_daily_ingestion(day)` elabora un giorno di pubblicazione TED e registra l'esecuzione in
`ingestion_runs` (stato `running`, poi `success` o `failed` con i conteggi). `run_pending_days`
recupera i giorni mancanti (ADR-009): elabora in ordine ogni giorno fino a ieri senza
un'esecuzione riuscita, dal giorno dopo l'ultimo riuscito (al primo avvio solo ieri).
Due esecuzioni contemporanee non sono ammesse: lock nel processo e riga `running` nel database
(una riga `running` più vecchia di `STALE_RUN_AFTER` è considerata interrotta e chiusa `failed`).
"""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from backend.domain import repository
from backend.domain.config import (
    DocumentsConfig,
    FiltersConfig,
    ScoringConfig,
    load_documents_config,
    load_filters_config,
    load_scoring_config,
)
from backend.domain.database import create_db_engine, create_session_factory
from backend.domain.documents import process_tender_documents
from backend.domain.filters import apply_filters
from backend.domain.models import IngestionRun, RunStatus
from backend.domain.scoring import evaluate_tender
from backend.ingestion.dedup import ChainLookupError, NoticeLookup, TedNoticeLookup, save_notice
from backend.ingestion.parser import parse_notices
from backend.ingestion.ted_client import TedClient

logger = logging.getLogger(__name__)

ROME = ZoneInfo("Europe/Rome")
STALE_RUN_AFTER = timedelta(hours=6)
MAX_RECOVERY_DAYS = 30
_process_lock = threading.Lock()


class RunAlreadyRunningError(RuntimeError):
    """Un'altra esecuzione del job è in corso: la nuova viene rifiutata."""


@dataclass
class PipelineDeps:
    """Dipendenze del job, sostituibili nei test. I valori `None` usano quelli reali."""

    session_factory: sessionmaker[Session] | None = None
    fetch_notices: Callable[[date], list[dict[str, Any]]] | None = None
    lookup: NoticeLookup | None = None
    filters_config: FiltersConfig | None = None
    scoring_config: ScoringConfig | None = None
    documents_config: DocumentsConfig | None = None
    process_documents: Callable[..., Any] = process_tender_documents
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


@dataclass
class RunSummary:
    """Esito di un'esecuzione, uguale a quanto salvato in `ingestion_runs`."""

    run_id: int
    run_date: date
    status: RunStatus
    fetched_count: int = 0
    new_count: int = 0
    updated_count: int = 0
    relevant_count: int = 0
    skipped_count: int = 0
    error_message: str | None = None


def yesterday(now: datetime) -> date:
    """Giorno precedente secondo il fuso Europe/Rome."""
    return now.astimezone(ROME).date() - timedelta(days=1)


def days_to_process(last_success: date | None, today_rome: date) -> list[date]:
    """Giorni da elaborare fino a ieri, dal giorno dopo l'ultimo riuscito (ADR-009).

    Al primo avvio (`last_success` assente) solo ieri; al massimo `MAX_RECOVERY_DAYS` giorni.
    """
    end = today_rome - timedelta(days=1)
    start = end if last_success is None else last_success + timedelta(days=1)
    start = max(start, end - timedelta(days=MAX_RECOVERY_DAYS - 1))
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def utc_now(deps: PipelineDeps) -> datetime:
    """Momento attuale in UTC: i tempi si salvano sempre in UTC (SQLite non conserva il fuso)."""
    return deps.now().astimezone(UTC)


def _resolve(deps: PipelineDeps) -> PipelineDeps:
    """Completa le dipendenze mancanti con quelle reali (database, TED, configurazione)."""
    session_factory = deps.session_factory or create_session_factory(create_db_engine())
    fetch = deps.fetch_notices
    lookup = deps.lookup
    if fetch is None or lookup is None:
        client = TedClient()
        fetch = fetch or client.fetch_notices
        lookup = lookup or TedNoticeLookup(client.search)
    return PipelineDeps(
        session_factory=session_factory,
        fetch_notices=fetch,
        lookup=lookup,
        filters_config=deps.filters_config or load_filters_config(),
        scoring_config=deps.scoring_config or load_scoring_config(),
        documents_config=deps.documents_config or load_documents_config(),
        process_documents=deps.process_documents,
        now=deps.now,
    )


@contextmanager
def exclusive_run() -> Iterator[None]:
    """Lock del processo: una sola esecuzione alla volta (la seconda è rifiutata, non attende)."""
    if not _process_lock.acquire(blocking=False):
        raise RunAlreadyRunningError("Un'esecuzione del job è già in corso in questo processo.")
    try:
        yield
    finally:
        _process_lock.release()


def _claim_run(session: Session, run_date: date, now: datetime) -> IngestionRun:
    """Crea la riga `running`, rifiutando se un'altra esecuzione recente è in corso."""
    running = repository.get_running_run(session)
    if running is not None:
        started = running.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if now - started < STALE_RUN_AFTER:
            raise RunAlreadyRunningError(
                f"Esecuzione {running.id} per il {running.run_date} in corso "
                f"dal {started:%Y-%m-%d %H:%M} UTC."
            )
        logger.warning(
            "Esecuzione %s interrotta (running da oltre %s): chiusa failed",
            running.id,
            STALE_RUN_AFTER,
        )
        repository.finish_run(
            session,
            running,
            status=RunStatus.FAILED,
            error_message="Esecuzione interrotta: nessuna chiusura entro il tempo massimo.",
            now=now,
        )
    run = repository.start_run(session, run_date, now=now)
    session.commit()
    return run


def _process_day(session: Session, run_date: date, deps: PipelineDeps, summary: RunSummary) -> None:
    assert deps.fetch_notices and deps.lookup and deps.filters_config and deps.scoring_config
    raw_notices = deps.fetch_notices(run_date)
    summary.fetched_count = len(raw_notices)
    tenders = parse_notices(raw_notices)
    summary.skipped_count = len(raw_notices) - len(tenders)
    now = deps.now()
    for tender in tenders:
        buyer_country = tender.raw_data.get("buyer-country")
        filter_result = apply_filters(
            tender, buyer_country=buyer_country, config=deps.filters_config, now=now
        )
        evaluation = evaluate_tender(tender, filter_result, deps.scoring_config, now)
        try:
            with session.begin_nested():
                outcome = save_notice(session, tender, evaluation, deps.lookup)
        except ChainLookupError as exc:
            # La rettifica si riprova alla prossima esecuzione: nulla è stato salvato.
            summary.skipped_count += 1
            logger.warning("Avviso %s non salvato: %s", tender.publication_number, exc)
            continue
        if outcome.skipped_as_older:
            continue
        if outcome.created:
            summary.new_count += 1
        else:
            summary.updated_count += 1
        if outcome.tender.is_relevant:
            summary.relevant_count += 1
            deps.process_documents(session, outcome.tender, config=deps.documents_config)
        session.commit()


def run_daily_ingestion(run_date: date, deps: PipelineDeps | None = None) -> RunSummary:
    """Elabora gli avvisi TED di `run_date` e registra l'esecuzione in `ingestion_runs`.

    Solleva `RunAlreadyRunningError` se un'altra esecuzione è in corso; ogni altro errore
    chiude l'esecuzione `failed` con un messaggio leggibile e viene restituito nel riepilogo.
    """
    resolved = _resolve(deps or PipelineDeps())
    assert resolved.session_factory is not None
    with exclusive_run(), resolved.session_factory() as session:
        run = _claim_run(session, run_date, utc_now(resolved))
        summary = RunSummary(run_id=run.id, run_date=run_date, status=RunStatus.RUNNING)
        logger.info("Esecuzione %s avviata per il %s", run.id, run_date.isoformat())
        try:
            _process_day(session, run_date, resolved, summary)
        except Exception as exc:
            session.rollback()
            summary.status = RunStatus.FAILED
            summary.error_message = f"{exc.__class__.__name__}: {exc}"[:2000]
            logger.exception("Esecuzione %s fallita", run.id)
        else:
            summary.status = RunStatus.SUCCESS
        run = session.get(IngestionRun, summary.run_id) or run
        repository.finish_run(
            session,
            run,
            status=summary.status,
            fetched_count=summary.fetched_count,
            new_count=summary.new_count,
            updated_count=summary.updated_count,
            relevant_count=summary.relevant_count,
            error_message=summary.error_message,
            now=utc_now(resolved),
        )
        session.commit()
        logger.info(
            "Esecuzione %s terminata: %s (raccolti %d, nuovi %d, aggiornati %d, rilevanti %d)",
            run.id,
            summary.status.value,
            summary.fetched_count,
            summary.new_count,
            summary.updated_count,
            summary.relevant_count,
        )
        return summary


def run_pending_days(deps: PipelineDeps | None = None) -> list[RunSummary]:
    """Esegue il job per ogni giorno mancante fino a ieri (recupero dei giorni falliti).

    Si ferma al primo giorno fallito, che verrà ripreso alla prossima esecuzione.
    """
    resolved = _resolve(deps or PipelineDeps())
    assert resolved.session_factory is not None
    with resolved.session_factory() as session:
        last_success = repository.last_successful_run_date(session)
    pending = days_to_process(last_success, resolved.now().astimezone(ROME).date())
    summaries = []
    for day in pending:
        summary = run_daily_ingestion(day, resolved)
        summaries.append(summary)
        if summary.status is RunStatus.FAILED:
            break
    return summaries
