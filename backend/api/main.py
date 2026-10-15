"""Applicazione FastAPI di Radar Gare IT.

Avvio locale: `uvicorn backend.api.main:app --reload` (ambiente virtuale attivo).
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import reports, runs, stats, tenders
from backend.api.errors import register_error_handlers
from backend.api.schemas import Health
from backend.ingestion.logging_config import configure_logging
from backend.ingestion.scheduler import start_scheduler

logger = logging.getLogger(__name__)

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:5173"


def scheduler_enabled() -> bool:
    """Lo scheduler giornaliero parte solo con `ENABLE_SCHEDULER=true` (predefinito: spento)."""
    return os.environ.get("ENABLE_SCHEDULER", "").strip().lower() == "true"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Ciclo di vita dell'app: log JSON e, se abilitato, scheduler del job di ingestion.

    Lo scheduler ha il lock solo nel processo: l'app va eseguita con un solo worker.
    """
    configure_logging()
    scheduler = start_scheduler() if scheduler_enabled() else None
    if scheduler is None:
        logger.info("Scheduler del job giornaliero disattivato (ENABLE_SCHEDULER non è true)")
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    """Crea l'applicazione con router, CORS, handler degli errori e ciclo di vita."""
    app = FastAPI(
        lifespan=lifespan,
        title="Radar Gare IT API",
        version="1.0.0",
        description="Gare IT con ente appaltante italiano raccolte da TED. "
        "Contratto: docs/API_CONTRACT.yaml.",
    )
    # Variabile assente o vuota (es. `CORS_ORIGINS=` nel file locale): valgono le predefinite.
    origins = (os.environ.get("CORS_ORIGINS") or DEFAULT_CORS_ORIGINS).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in origins if o.strip()],
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    for module in (tenders, reports, stats, runs):
        app.include_router(module.router)

    @app.get("/health", operation_id="getHealth", summary="Verifica che il servizio sia attivo")
    def health() -> Health:
        return Health(status="ok")

    return app


app = create_app()
