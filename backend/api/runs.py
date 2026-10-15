"""Endpoint dello storico e dell'avvio manuale delle esecuzioni."""

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.api.convert import aware
from backend.api.deps import get_now, get_pipeline_deps, get_session, session_factory
from backend.api.errors import ApiError, error_responses
from backend.api.schemas import Run, RunAccepted, RunList
from backend.domain import repository
from backend.domain.models import IngestionRun
from backend.domain.repository import InvalidQueryError
from backend.ingestion import pipeline
from backend.ingestion.pipeline import PipelineDeps, RunAlreadyRunningError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["runs"])

# Attesa massima della riga `running` appena creata dal job (poi risposta 500).
START_TIMEOUT_SECONDS = 15.0
RECENT_RUNS = 100  # esecuzioni lette per riconoscere quelle create dal job
POLL_SECONDS = 0.02

# Un solo avvio alla volta: il lock del job vale solo nel processo (un solo worker).
_launch_lock = threading.Lock()
_job_thread: threading.Thread | None = None


def run_from_model(run: IngestionRun) -> Run:
    """Converte l'esecuzione del dominio nello schema del contratto (datetime con fuso)."""
    return Run(
        id=run.id,
        run_date=run.run_date,
        started_at=aware(run.started_at),
        finished_at=aware(run.finished_at) if run.finished_at else None,
        status=run.status.value,
        fetched_count=run.fetched_count,
        new_count=run.new_count,
        updated_count=run.updated_count,
        relevant_count=run.relevant_count,
        error_message=run.error_message,
    )


@router.get(
    "/runs",
    operation_id="listRuns",
    summary="Storico delle esecuzioni",
    response_model=RunList,
    responses=error_responses(422),
)
def list_runs(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RunList:
    try:
        runs = repository.list_runs(session, limit)
    except InvalidQueryError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    return RunList(items=[run_from_model(r) for r in runs])


def _job(deps: PipelineDeps | None, failure: list[BaseException]) -> None:
    """Corpo del thread: recupera i giorni mancanti o, se non ce ne sono, rielabora ieri.

    Salva in `failure` l'eventuale eccezione (es. `RunAlreadyRunningError`) per l'API.
    """
    try:
        resolved = deps or PipelineDeps()
        factory = (
            resolved.session_factory or session_factory()
        )  # factory in cache, non un engine nuovo
        resolved = replace(resolved, session_factory=factory)
        today = resolved.now().astimezone(pipeline.ROME).date()
        with factory() as session:
            last_success = repository.last_successful_run_date(session)
        if pipeline.days_to_process(last_success, today):
            if not pipeline.run_pending_days(resolved):
                # Con giorni da recuperare, nessun riepilogo = il job si è fermato per il lock.
                raise RunAlreadyRunningError("Un'altra esecuzione del job è in corso.")
        else:
            # Niente da recuperare: l'avvio manuale rielabora comunque ieri (è idempotente).
            pipeline.run_daily_ingestion(today - timedelta(days=1), resolved)
    except Exception as exc:
        failure.append(exc)
        logger.exception("Esecuzione manuale non riuscita")


def _latest_run_id(session: Session) -> int:
    """Id più alto tra le esecuzioni recenti (0 se non ce ne sono): serve a riconoscere le nuove."""
    return max((r.id for r in repository.list_runs(session, RECENT_RUNS)), default=0)


def _already_running(run_id: int | None) -> ApiError:
    detail = f"L'esecuzione {run_id} è già in corso." if run_id else "Un'esecuzione è già in corso."
    return ApiError(409, "run_in_progress", detail)


@contextmanager
def _exclusive_launch() -> Iterator[None]:
    """Un solo avvio alla volta: se un'altra richiesta sta già avviando il job risponde 409 subito,
    senza attendere (le richieste non si accodano)."""
    if not _launch_lock.acquire(blocking=False):
        raise _already_running(None)
    try:
        yield
    finally:
        _launch_lock.release()


def wait_for_job(timeout: float) -> bool:
    """Attende il thread dell'ultima esecuzione manuale; `True` se non è più attivo."""
    thread = _job_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout)
    return thread is None or not thread.is_alive()


@router.post(
    "/runs",
    operation_id="startRun",
    summary="Avvio manuale del monitoraggio",
    status_code=202,
    response_model=RunAccepted,
    responses=error_responses(409),
)
def start_run(
    session: Annotated[Session, Depends(get_session)],
    pipeline_deps: Annotated[PipelineDeps | None, Depends(get_pipeline_deps)],
    now: Annotated[datetime, Depends(get_now)],
) -> RunAccepted:
    global _job_thread
    with _exclusive_launch():
        running = repository.get_running_run(session)
        if running is not None and now - aware(running.started_at) < pipeline.STALE_RUN_AFTER:
            raise _already_running(running.id)
        if _job_thread is not None and _job_thread.is_alive():
            raise _already_running(None)

        baseline = _latest_run_id(session)
        failure: list[BaseException] = []
        thread = threading.Thread(
            target=_job, args=(pipeline_deps, failure), name="manual-run", daemon=True
        )
        _job_thread = thread
        thread.start()

        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while True:
            # Prima si controlla il thread, poi si legge: se era già terminato la lettura che segue
            # è definitiva (la riga, se creata, c'è). Al contrario si rischierebbe di perderla.
            alive = thread.is_alive()
            session.rollback()  # chiude lo snapshot: la riga creata dal thread deve essere visibile
            created = [r.id for r in repository.list_runs(session, RECENT_RUNS) if r.id > baseline]
            if created:
                # La prima riga creata dal job è la più bassa tra le nuove.
                return RunAccepted(id=min(created), status="running")
            if not alive:
                break
            if time.monotonic() > deadline:
                break
            time.sleep(POLL_SECONDS)

        # Nessuna nuova esecuzione: il job è finito o non è partito.
        if failure and isinstance(failure[0], RunAlreadyRunningError):
            session.rollback()
            running = repository.get_running_run(session)
            raise _already_running(running.id if running else None)
        raise RuntimeError("L'esecuzione manuale non è partita entro il tempo previsto.")
