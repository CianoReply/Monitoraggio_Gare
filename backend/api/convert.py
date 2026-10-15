"""Conversioni condivise tra oggetti del dominio e schemi dell'API."""

from datetime import UTC, datetime


def aware(value: datetime) -> datetime:
    """SQLite restituisce datetime senza fuso: sono sempre UTC (il dominio salva in UTC)."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
