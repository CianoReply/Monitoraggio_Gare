"""Programmazione del job giornaliero con APScheduler 3.x (T1.5).

Ogni giorno all'orario `INGESTION_SCHEDULE` (predefinito 06:00, fuso Europe/Rome) esegue
`run_pending_days`, che elabora ieri e gli eventuali giorni mancanti. Lo scheduler si avvia
dall'applicazione (T4.1) con `start_scheduler()`; non parte da solo all'import.
"""

import logging
import os
from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.ingestion.pipeline import ROME, RunAlreadyRunningError, run_pending_days

logger = logging.getLogger(__name__)

JOB_ID = "daily_ingestion"
DEFAULT_SCHEDULE = "06:00"


def parse_schedule(value: str | None) -> tuple[int, int]:
    """Converte `HH:MM` in (ora, minuti); valore vuoto = 06:00. `ValueError` se non valido."""
    text = (value or "").strip() or DEFAULT_SCHEDULE
    try:
        hour_text, minute_text = text.split(":")
        hour, minute = int(hour_text), int(minute_text)
    except ValueError as exc:
        raise ValueError(f"INGESTION_SCHEDULE non valido: {text!r} (atteso HH:MM)") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"INGESTION_SCHEDULE fuori intervallo: {text!r}")
    return hour, minute


def daily_job(job: Callable[[], Any] = run_pending_days) -> None:
    """Esegue il job; un'esecuzione già in corso non è un errore dello scheduler."""
    try:
        job()
    except RunAlreadyRunningError as exc:
        logger.warning("Job giornaliero saltato: %s", exc)


def create_scheduler(
    hour: int,
    minute: int,
    job: Callable[[], Any] = daily_job,
    scheduler: BackgroundScheduler | None = None,
    second: int = 0,
) -> BackgroundScheduler:
    """Crea lo scheduler con il job giornaliero all'orario indicato (Europe/Rome), non avviato."""
    scheduler = scheduler or BackgroundScheduler(timezone=ROME)
    scheduler.add_job(
        job,
        CronTrigger(hour=hour, minute=minute, second=second, timezone=ROME),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Crea e avvia lo scheduler con l'orario di `INGESTION_SCHEDULE`."""
    hour, minute = parse_schedule(os.environ.get("INGESTION_SCHEDULE"))
    scheduler = create_scheduler(hour, minute)
    scheduler.start()
    logger.info("Job giornaliero programmato alle %02d:%02d (Europe/Rome)", hour, minute)
    return scheduler
