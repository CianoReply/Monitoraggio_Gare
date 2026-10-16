"""Applicazione FastAPI di Radar Gare IT.

Avvio locale: `uvicorn backend.api.main:app --reload` (ambiente virtuale attivo).

L'API non ha autenticazione: va esposta solo su 127.0.0.1 o su una rete fidata (vedi
backend/api/CLAUDE.md). Variabili: `CORS_ORIGINS`, `ALLOWED_HOSTS`, `DOCS_ENABLED`,
`ENABLE_SCHEDULER`.
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.api import deps, frontend, reports, runs, stats, tenders
from backend.api.errors import register_error_handlers
from backend.api.schemas import Health
from backend.domain import repository
from backend.domain.models import RunStatus
from backend.ingestion.logging_config import configure_logging
from backend.ingestion.scheduler import start_scheduler

logger = logging.getLogger(__name__)

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:5173"
DEFAULT_ALLOWED_HOSTS = "localhost,127.0.0.1,testserver"
CORS_ALLOWED_HEADERS = ["Content-Type", "Accept", "X-User-Name"]
SHUTDOWN_WAIT_SECONDS = 5.0  # attesa massima del job manuale alla chiusura dell'app
RESTART_ERROR_MESSAGE = "Esecuzione interrotta da un riavvio"
MAX_INTERRUPTED_RUNS = 100


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def cors_origins() -> list[str]:
    """Origini del frontend da `CORS_ORIGINS` (assente o vuota = predefinite). `*` è vietato."""
    origins = _split_csv(os.environ.get("CORS_ORIGINS") or DEFAULT_CORS_ORIGINS)
    if "*" in origins:
        raise ValueError(
            "CORS_ORIGINS non può contenere '*': elencare le origini ammesse del frontend."
        )
    return origins


def allowed_hosts() -> list[str]:
    """Host ammessi nell'intestazione Host da `ALLOWED_HOSTS` (assente o vuota = predefiniti)."""
    return _split_csv(os.environ.get("ALLOWED_HOSTS") or DEFAULT_ALLOWED_HOSTS)


def docs_enabled() -> bool:
    """`/docs`, `/redoc` e `/openapi.json` sono attivi salvo `DOCS_ENABLED=false` (o 0, no, off)."""
    value = os.environ.get("DOCS_ENABLED", "").strip().lower()
    return value not in {"false", "0", "no", "off"}


def scheduler_enabled() -> bool:
    """Lo scheduler giornaliero parte solo con `ENABLE_SCHEDULER=true` (predefinito: spento)."""
    return os.environ.get("ENABLE_SCHEDULER", "").strip().lower() == "true"


class AllowedHostsMiddleware:
    """Rifiuta con 400 le richieste il cui Host non è nell'elenco (anti DNS rebinding).

    Come `TrustedHostMiddleware` di Starlette, ma risponde nel formato `{error, message}`.
    Supporta il nome esatto, il carattere jolly iniziale (`*.example.com`) e `*`.
    """

    def __init__(self, app: ASGIApp, allowed: list[str]) -> None:
        self.app = app
        self.allowed = [host.lower() for host in allowed]

    def _is_allowed(self, host: str) -> bool:
        for pattern in self.allowed:
            if pattern == "*" or host == pattern:
                return True
            if pattern.startswith("*.") and host.endswith(pattern[1:]):
                return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            raw = Headers(scope=scope).get("host", "").lower()
            host = raw.split("]")[0] + "]" if raw.startswith("[") else raw.split(":")[0]
            if not self._is_allowed(host):
                response = JSONResponse(
                    status_code=400,
                    content={"error": "invalid_host", "message": "Host non ammesso."},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def close_interrupted_runs(factory: Callable[[], Session]) -> int:
    """Chiude `failed` le esecuzioni rimaste `running` (processo precedente terminato).

    Si chiama all'avvio, con un solo worker: nessuna esecuzione può essere davvero in corso.
    """
    closed = 0
    with factory() as session:
        while closed < MAX_INTERRUPTED_RUNS:
            running = repository.get_running_run(session)
            if running is None:
                break
            repository.finish_run(
                session,
                running,
                status=RunStatus.FAILED,
                error_message=RESTART_ERROR_MESSAGE,
                now=datetime.now(UTC),
            )
            session.commit()
            closed += 1
    return closed


def make_lifespan(session_factory: sessionmaker[Session] | None = None):  # type: ignore[no-untyped-def]
    """Ciclo di vita: log JSON, chiusura delle esecuzioni interrotte, scheduler opzionale.

    Lo scheduler ha il lock solo nel processo: l'app va eseguita con un solo worker.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        try:
            factory = session_factory or deps.session_factory()
            closed = close_interrupted_runs(factory)
            if closed:
                logger.warning("Chiuse come failed %d esecuzioni rimaste running", closed)
        except Exception:
            # Database non configurato o non raggiungibile: l'app parte comunque (si vedrà
            # alla prima richiesta); non si nascondono però le cause.
            logger.exception("Impossibile chiudere le esecuzioni interrotte all'avvio")
        scheduler = start_scheduler() if scheduler_enabled() else None
        if scheduler is None:
            logger.info("Scheduler del job giornaliero disattivato (ENABLE_SCHEDULER non è true)")
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            finished = await asyncio.to_thread(runs.wait_for_job, SHUTDOWN_WAIT_SECONDS)
            if not finished:
                logger.warning("Esecuzione manuale ancora in corso alla chiusura dell'app")

    return lifespan


def create_app(session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    """Crea l'applicazione con router, CORS, host ammessi, handler degli errori e ciclo di vita.

    `session_factory` serve solo ai test (database diverso da `DATABASE_URL` all'avvio).
    """
    docs = docs_enabled()
    app = FastAPI(
        lifespan=make_lifespan(session_factory),
        title="Radar Gare IT API",
        version="1.0.0",
        description="Gare IT con ente appaltante italiano raccolte da TED. "
        "Contratto: docs/API_CONTRACT.yaml.",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_methods=["GET", "POST", "PATCH", "PUT"],
        allow_headers=CORS_ALLOWED_HEADERS,
    )
    # Ultimo aggiunto = più esterno: gli host non ammessi sono rifiutati prima del resto.
    app.add_middleware(AllowedHostsMiddleware, allowed=allowed_hosts())
    register_error_handlers(app)
    for module in (tenders, reports, stats, runs, frontend):
        app.include_router(module.router)

    @app.get("/health", operation_id="getHealth", summary="Verifica che il servizio sia attivo")
    def health() -> Health:
        return Health(status="ok")

    return app


app = create_app()
