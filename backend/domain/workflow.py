"""Lavoro dell'utente sulle gare (ADR-016): osservazione, decisioni e liste del frontend.

Regole (allineate al simulatore del frontend, `Monitoraggio_Gare_FE/src/mocks/db.ts`):
- una gara entra in osservazione con uno stato diverso da `none`; `watched_at` si imposta quando
  la gara diventa attiva (non era osservata o la scadenza era passata), non si azzera con `none`;
- una decisione sostituisce la precedente e registra chi e quando;
- "in osservazione" = stato attivo e scadenza non passata (giorno di Roma; senza scadenza: attiva).
Come il resto del dominio fa solo `flush`: il `commit` è di chi chiama.
"""

from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.domain.models import DecisionStatus, Tender, WatchStatus
from backend.domain.repository import list_tenders
from backend.domain.timeutil import ROME, as_utc

ACTIVE_WATCH: tuple[WatchStatus, ...] = (
    WatchStatus.WATCHING,
    WatchStatus.TO_DEEPEN,
    WatchStatus.CANDIDATE,
    WatchStatus.DISCARDED,
)
MAX_REASON = 2000
MAX_USER = 200
SEARCH_LIMIT = 50


def _rome_day_start(day: date) -> datetime:
    return as_utc(datetime(day.year, day.month, day.day, tzinfo=ROME))


def is_active_watch(tender: Tender, today: date) -> bool:
    """Gara in osservazione attiva: stato attivo e scadenza non passata (giorno di Roma)."""
    if tender.watch_status not in ACTIVE_WATCH:
        return False
    deadline = tender.submission_deadline
    return deadline is None or deadline.astimezone(ROME).date() >= today


def set_watch(
    session: Session, tender: Tender, status: WatchStatus, now: datetime | None = None
) -> Tender:
    """Imposta lo stato di osservazione della gara."""
    moment = as_utc(now)
    today = moment.astimezone(ROME).date()
    if status is not WatchStatus.NONE and not is_active_watch(tender, today):
        tender.watched_at = moment
    tender.watch_status = status
    session.flush()
    return tender


def set_decision(
    session: Session,
    tender: Tender,
    status: DecisionStatus,
    reason: str,
    decided_by: str,
    now: datetime | None = None,
) -> Tender:
    """Registra la decisione sulla gara (sostituisce l'eventuale precedente)."""
    if "\x00" in reason or "\x00" in decided_by:
        raise ValueError("Testo non valido: contiene il carattere NUL")
    if len(reason) > MAX_REASON:
        raise ValueError(f"Motivo troppo lungo (massimo {MAX_REASON} caratteri)")
    if not decided_by.strip() or len(decided_by) > MAX_USER:
        raise ValueError(f"Autore della decisione mancante o oltre {MAX_USER} caratteri")
    tender.decision_status = status
    tender.decision_reason = reason
    tender.decided_by = decided_by.strip()
    tender.decided_at = as_utc(now)
    session.flush()
    return tender


def list_published_on(session: Session, day: date) -> Sequence[Tender]:
    """Gare non scartate pubblicate su TED nel giorno indicato, dalla più pertinente."""
    query = (
        select(Tender)
        .where(Tender.publication_date == day, Tender.discard_reason.is_(None))
        .order_by(
            Tender.relevance_score.desc(),
            Tender.submission_deadline.is_(None),
            Tender.submission_deadline.asc(),
            Tender.id.asc(),
        )
    )
    return session.scalars(query).all()


def list_active_watch(session: Session, today: date) -> Sequence[Tender]:
    """Gare in osservazione attiva, dalla scadenza più vicina (senza scadenza in fondo)."""
    query = (
        select(Tender)
        .where(
            Tender.watch_status.in_(ACTIVE_WATCH),
            or_(
                Tender.submission_deadline.is_(None),
                Tender.submission_deadline >= _rome_day_start(today),
            ),
        )
        .order_by(
            Tender.submission_deadline.is_(None),
            Tender.submission_deadline.asc(),
            Tender.id.asc(),
        )
    )
    return session.scalars(query).all()


def list_decided(session: Session) -> Sequence[Tender]:
    """Gare con una decisione, dalla più recente."""
    query = (
        select(Tender)
        .where(Tender.decision_status.is_not(None))
        .order_by(Tender.decided_at.desc(), Tender.id.desc())
    )
    return session.scalars(query).all()


def search(session: Session, text: str, limit: int = SEARCH_LIMIT) -> list[Tender]:
    """Ricerca su titolo, descrizione ed ente (anche gare scartate), dalla più pertinente."""
    query = text.strip()
    if not query:
        return []
    page = list_tenders(session, q=query[:200], include_discarded=True, page_size=limit)
    return [row.tender for row in page.items]
