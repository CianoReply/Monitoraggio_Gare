"""Applicazione FastAPI di Radar Gare IT.

Avvio locale: `uvicorn backend.api.main:app --reload` (ambiente virtuale attivo).
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import reports, runs, stats, tenders
from backend.api.errors import register_error_handlers
from backend.api.schemas import Health

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://localhost:5173"


def create_app() -> FastAPI:
    """Crea l'applicazione con router, CORS e handler degli errori."""
    app = FastAPI(
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
