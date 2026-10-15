"""Creazione di engine e sessioni. Il database si configura con la variabile `DATABASE_URL`."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def get_database_url() -> str:
    """Legge `DATABASE_URL` dall'ambiente (mai da file `.env`)."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("Variabile d'ambiente DATABASE_URL non impostata")
    return url


def create_db_engine(url: str | None = None) -> Engine:
    """Crea l'engine; senza argomenti usa `DATABASE_URL`."""
    return create_engine(url or get_database_url())


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Factory di sessioni; `expire_on_commit=False` per usare gli oggetti dopo il commit."""
    return sessionmaker(bind=engine, expire_on_commit=False)
