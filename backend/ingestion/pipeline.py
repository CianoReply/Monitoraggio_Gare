"""Job giornaliero di raccolta (T1.5): TED → parser → filtri e punteggio → salvataggio → documenti.

`run_daily_ingestion(day)` elabora un giorno di pubblicazione TED e registra l'esecuzione in
`ingestion_runs` (stato `running`, poi `success` o `failed` con i conteggi). `run_pending_days`
recupera i giorni mancanti (ADR-009): elabora in ordine ogni giorno fino a ieri senza
un'esecuzione riuscita, dal giorno dopo l'ultimo riuscito (al primo avvio solo ieri).
Due esecuzioni contemporanee non sono ammesse: lock nel processo e riga `running` nel database
(una riga `running` più vecchia di `STALE_RUN_AFTER` è considerata interrotta e chiusa `failed`).
"""

import logging
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
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
from backend.domain.schemas import TenderCreate
from backend.domain.scoring import evaluate_tender
from backend.ingestion.dedup import ChainLookupError, NoticeLookup, TedNoticeLookup, save_notice
from backend.ingestion.parser import parse_notices
from backend.ingestion.ted_client import TedClient

logger = logging.getLogger(__name__)

ROME = ZoneInfo("Europe/Rome")
STALE_RUN_AFTER = timedelta(hours=6)
MAX_RECOVERY_DAYS = 30
_process_lock = threading.Lock()
_URL_PATTERN = re.compile(r"https?://\S+")


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
    documents_failed_count: int = 0
    unresolved_changes: int = 0
    error_message: str | None = None


def days_to_process(last_success: date | None, today_rome: date) -> list[date]:
    """Giorni da elaborare fino a ieri, dal giorno dopo l'ultimo riuscito (ADR-009).

    Al primo avvio (`last_success` assente) solo ieri; al massimo `MAX_RECOVERY_DAYS` giorni,
    con un warning se la finestra taglia giorni più vecchi. Un giorno rimasto senza successo
    prima dell'ultimo riuscito non viene ripreso (ADR-009: si parte dall'ultimo riuscito).
    """
    end = today_rome - timedelta(days=1)
    start = end if last_success is None else last_success + timedelta(days=1)
    window_start = end - timedelta(days=MAX_RECOVERY_DAYS - 1)
    if start < window_start:
        logger.warning(
            "Recupero limitato a %d giorni: i giorni dal %s al %s non saranno elaborati",
            MAX_RECOVERY_DAYS,
            start.isoformat(),
            (window_start - timedelta(days=1)).isoformat(),
        )
        start = window_start
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def public_error_message(exc: BaseException) -> str:
    """Messaggio d'errore da salvare in `ingestion_runs` (visibile da `GET /runs`).

    Il dettaglio completo resta nel log. Gli errori del database diventano un messaggio
    generico (possono contenere query e parametri); gli URL sono oscurati.
    """
    name = exc.__class__.__name__
    if isinstance(exc, SQLAlchemyError):
        return f"{name}: errore del database (dettagli nel log)"
    text = _URL_PATTERN.sub("<url>", str(exc)).strip()
    return f"{name}: {text}"[:500] if text else name


def utc_now(deps: PipelineDeps) -> datetime:
    """Momento attuale in UTC: i tempi si salvano sempre in UTC (SQLite non conserva il fuso)."""
    return deps.now().astimezone(UTC)


@lru_cache(maxsize=1)
def _default_session_factory() -> sessionmaker[Session]:
    """Engine e sessioni del database reale, creati una volta per processo."""
    return create_session_factory(create_db_engine())


@lru_cache(maxsize=1)
def _default_ted_client() -> TedClient:
    """Client TED riusato tra le esecuzioni dello stesso processo (connessioni HTTP comprese)."""
    return TedClient()


def _resolve(deps: PipelineDeps) -> PipelineDeps:
    """Completa le dipendenze mancanti con quelle reali (database, TED, configurazione)."""
    session_factory = deps.session_factory or _default_session_factory()
    fetch = deps.fetch_notices
    lookup = deps.lookup
    if fetch is None or lookup is None:
        client = _default_ted_client()
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


def _process_notice(
    session: Session, tender: TenderCreate, deps: PipelineDeps, now: datetime, summary: RunSummary
) -> None:
    """Un avviso: filtri e punteggio prima del salvataggio (servono a `upsert_tender`, ADR-010),
    salvataggio con deduplica in un savepoint e commit; poi, fuori dalla transazione della gara,
    i documenti (download di rete anche lunghi): un loro errore non annulla la gara salvata."""
    if deps.lookup is None or deps.filters_config is None or deps.scoring_config is None:
        raise RuntimeError("Dipendenze del job non risolte")
    filter_result = apply_filters(
        tender,
        buyer_country=tender.raw_data.get("buyer-country"),
        config=deps.filters_config,
        now=now,
    )
    evaluation = evaluate_tender(tender, filter_result, deps.scoring_config, now)
    with session.begin_nested():
        outcome = save_notice(session, tender, evaluation, deps.lookup)
    session.commit()
    if outcome.skipped_as_older:
        return
    if outcome.created:
        summary.new_count += 1
    else:
        summary.updated_count += 1
    if outcome.tender.is_relevant:
        summary.relevant_count += 1
        try:
            with session.begin_nested():
                deps.process_documents(session, outcome.tender, config=deps.documents_config)
            session.commit()
        except Exception:
            session.rollback()
            summary.documents_failed_count += 1
            logger.exception("Documenti della gara %s non elaborati", tender.publication_number)


def _process_day(session: Session, run_date: date, deps: PipelineDeps, summary: RunSummary) -> None:
    """Raccolta e lettura del giorno, poi un avviso alla volta.

    Un avviso che fallisce (lookup TED, dati anomali, documenti) è saltato e registrato: il giorno
    fallisce solo per errori di sistema (TED non raggiungibile, database non disponibile).
    """
    if deps.fetch_notices is None:
        raise RuntimeError("Dipendenze del job non risolte")
    raw_notices = deps.fetch_notices(run_date)
    summary.fetched_count = len(raw_notices)
    tenders = parse_notices(raw_notices)
    summary.skipped_count = len(raw_notices) - len(tenders)
    now = deps.now()
    for tender in tenders:
        try:
            _process_notice(session, tender, deps, now, summary)
        except ChainLookupError as exc:
            # Nulla è stato salvato: il giorno chiude `failed` (vedi run_daily_ingestion), così
            # il recupero lo rielabora e la rettifica viene ripresa.
            summary.skipped_count += 1
            summary.unresolved_changes += 1
            logger.warning("Avviso %s non salvato: %s", tender.publication_number, exc)
        except (DataError, IntegrityError):
            # Dato non accettato dal database (es. valore fuori scala): si salta solo l'avviso.
            session.rollback()
            summary.skipped_count += 1
            logger.exception("Avviso %s rifiutato dal database", tender.publication_number)
        except SQLAlchemyError:
            raise
        except Exception:
            summary.skipped_count += 1
            logger.exception("Avviso %s saltato per un errore inatteso", tender.publication_number)
        session.commit()


def _close_run(deps: PipelineDeps, summary: RunSummary) -> None:
    """Chiude la riga dell'esecuzione con una sessione nuova (anche se quella del job è rotta)."""
    if deps.session_factory is None:
        raise RuntimeError("Dipendenze del job non risolte")
    with deps.session_factory() as session:
        run = session.get(IngestionRun, summary.run_id)
        if run is None:  # pragma: no cover - la riga è stata creata e salvata da _claim_run
            return
        repository.finish_run(
            session,
            run,
            status=summary.status,
            fetched_count=summary.fetched_count,
            new_count=summary.new_count,
            updated_count=summary.updated_count,
            relevant_count=summary.relevant_count,
            error_message=summary.error_message,
            now=utc_now(deps),
        )
        session.commit()


def run_daily_ingestion(run_date: date, deps: PipelineDeps | None = None) -> RunSummary:
    """Elabora gli avvisi TED di `run_date` e registra l'esecuzione in `ingestion_runs`.

    Solleva `RunAlreadyRunningError` se un'altra esecuzione è in corso e `ValueError` per un
    giorno non ancora concluso (oggi o futuro, Europe/Rome). Ogni altro errore chiude
    l'esecuzione `failed` con un messaggio leggibile, restituito nel riepilogo; la riga si chiude
    anche se il processo viene interrotto (`finally`).
    Limite: il lock vale nel singolo processo e la riga `running` non ha un vincolo univoco,
    quindi l'applicazione va eseguita con un solo worker (backend/ingestion/CLAUDE.md).
    """
    resolved = _resolve(deps or PipelineDeps())
    if resolved.session_factory is None:
        raise RuntimeError("Dipendenze del job non risolte")
    if run_date >= resolved.now().astimezone(ROME).date():
        raise ValueError(f"Il giorno {run_date.isoformat()} non è ancora concluso (Europe/Rome).")
    with exclusive_run():
        with resolved.session_factory() as session:
            run = _claim_run(session, run_date, utc_now(resolved))
            run_id = run.id
        summary = RunSummary(run_id=run_id, run_date=run_date, status=RunStatus.FAILED)
        logger.info("Esecuzione %s avviata per il %s", run_id, run_date.isoformat())
        try:
            with resolved.session_factory() as session:
                _process_day(session, run_date, resolved, summary)
            if summary.unresolved_changes:
                raise ChainLookupError(
                    f"{summary.unresolved_changes} rettifiche non collegate (TED non ha risposto "
                    "alla ricerca dell'avviso originale): il giorno sarà rielaborato"
                )
            summary.status = RunStatus.SUCCESS
        except Exception as exc:
            summary.error_message = public_error_message(exc)
            logger.exception("Esecuzione %s fallita", run_id)
        finally:
            if summary.status is not RunStatus.SUCCESS and summary.error_message is None:
                summary.error_message = "Esecuzione interrotta prima della fine."
            try:
                _close_run(resolved, summary)
            except Exception:
                logger.exception("Impossibile chiudere l'esecuzione %s", run_id)
        logger.info(
            "Esecuzione %s terminata: %s (raccolti %d, nuovi %d, aggiornati %d, rilevanti %d, "
            "saltati %d)",
            run_id,
            summary.status.value,
            summary.fetched_count,
            summary.new_count,
            summary.updated_count,
            summary.relevant_count,
            summary.skipped_count,
        )
        return summary


def run_pending_days(deps: PipelineDeps | None = None) -> list[RunSummary]:
    """Esegue il job per ogni giorno mancante fino a ieri (recupero dei giorni falliti).

    Si ferma al primo giorno fallito, che verrà ripreso alla prossima esecuzione, e se un'altra
    esecuzione è in corso (restituisce comunque i riepiloghi già ottenuti).
    """
    resolved = _resolve(deps or PipelineDeps())
    if resolved.session_factory is None:
        raise RuntimeError("Dipendenze del job non risolte")
    with resolved.session_factory() as session:
        last_success = repository.last_successful_run_date(session)
    pending = days_to_process(last_success, resolved.now().astimezone(ROME).date())
    summaries: list[RunSummary] = []
    for day in pending:
        try:
            summary = run_daily_ingestion(day, resolved)
        except RunAlreadyRunningError as exc:
            logger.warning("Recupero interrotto: %s", exc)
            break
        summaries.append(summary)
        if summary.status is RunStatus.FAILED:
            break
    return summaries


def main(argv: list[str] | None = None) -> int:
    """Esecuzione manuale: `python -m backend.ingestion.pipeline [--date AAAA-MM-GG]`.

    Senza `--date` recupera i giorni mancanti fino a ieri; con `--date` elabora quel giorno.
    Restituisce 0 se tutte le esecuzioni sono riuscite, 1 altrimenti (2 se un'altra è in corso).
    """
    import argparse

    from backend.ingestion.logging_config import configure_logging

    parser = argparse.ArgumentParser(description="Job di raccolta delle gare da TED")
    parser.add_argument("--date", type=date.fromisoformat, help="giorno di pubblicazione TED")
    args = parser.parse_args(argv)
    configure_logging()
    try:
        summaries = [run_daily_ingestion(args.date)] if args.date else run_pending_days()
    except RunAlreadyRunningError as exc:
        logger.error("%s", exc)
        return 2
    return 0 if all(s.status is RunStatus.SUCCESS for s in summaries) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
