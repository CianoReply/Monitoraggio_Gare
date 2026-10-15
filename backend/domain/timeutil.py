"""Fusi orari e conversioni condivise dal dominio: una sola `ROME`, una sola regola per `now`."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")


def utcnow() -> datetime:
    """Istante corrente con fuso UTC."""
    return datetime.now(UTC)


def as_utc(moment: datetime | None) -> datetime:
    """Istante in UTC: `None` = adesso, senza fuso orario = `ValueError`.

    Serve a tutte le funzioni che ricevono un `now` iniettabile.
    """
    if moment is None:
        return utcnow()
    if moment.tzinfo is None:
        raise ValueError("now deve avere il fuso orario (datetime aware)")
    return moment.astimezone(UTC)
