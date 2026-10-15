"""Accesso ai dati: unico punto da cui gli altri moduli leggono e scrivono le gare.

Le funzioni usano la `Session` ricevuta e fanno solo `flush`: il `commit` spetta a chi
possiede la transazione (job di ingestion, endpoint API).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, NamedTuple

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from backend.domain.models import Report, ReportStatus, Tender, utcnow
from backend.domain.schemas import TenderCreate

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

SortKey = Literal["score_desc", "deadline_asc", "publication_date_desc", "value_desc"]


class UpsertResult(NamedTuple):
    tender: Tender
    created: bool


class TenderPage(NamedTuple):
    items: list[Tender]
    total: int
    page: int
    page_size: int


def upsert_tender(session: Session, data: TenderCreate) -> UpsertResult:
    """Inserisce la gara o, se `publication_number` esiste già, ne aggiorna i campi.

    Non tocca i campi calcolati (`relevance_score`, `is_relevant`, `discard_reason`):
    li scrivono filtri e punteggio. Restituisce la gara e `created=True` se è nuova.
    """
    tender = session.scalar(
        select(Tender).where(Tender.publication_number == data.publication_number)
    )
    values = data.model_dump()
    if tender is None:
        tender = Tender(**values)
        session.add(tender)
        session.flush()
        return UpsertResult(tender, True)
    for field, value in values.items():
        setattr(tender, field, value)
    tender.updated_at = utcnow()
    session.flush()
    return UpsertResult(tender, False)


def get_tender(session: Session, tender_id: int) -> Tender | None:
    """Gara per id interno, `None` se non esiste."""
    return session.get(Tender, tender_id)


def get_tender_by_publication_number(session: Session, publication_number: str) -> Tender | None:
    """Gara per numero di pubblicazione TED, `None` se non esiste."""
    return session.scalar(select(Tender).where(Tender.publication_number == publication_number))


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _order_by(sort: SortKey) -> list[ColumnElement]:
    """Ordinamento con i valori null in fondo, in modo identico su PostgreSQL e SQLite."""
    deadline_asc = [Tender.submission_deadline.is_(None), Tender.submission_deadline.asc()]
    if sort == "score_desc":
        order = [
            Tender.relevance_score.is_(None),
            Tender.relevance_score.desc(),
            *deadline_asc,
        ]
    elif sort == "deadline_asc":
        order = deadline_asc
    elif sort == "publication_date_desc":
        order = [Tender.publication_date.desc()]
    elif sort == "value_desc":
        order = [Tender.estimated_value.is_(None), Tender.estimated_value.desc()]
    else:
        raise ValueError(f"Ordinamento non valido: {sort!r}")
    return [*order, Tender.id.asc()]


def list_tenders(
    session: Session,
    *,
    min_score: int | None = None,
    is_relevant: bool | None = None,
    cpv: str | None = None,
    deadline_from: datetime | None = None,
    deadline_to: datetime | None = None,
    publication_from: date | None = None,
    publication_to: date | None = None,
    min_value: Decimal | None = None,
    max_value: Decimal | None = None,
    report_status: ReportStatus | None = None,
    q: str | None = None,
    sort: SortKey = "score_desc",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> TenderPage:
    """Elenco paginato di gare con filtri; tutti i filtri sono combinati in AND.

    - `cpv`: prefisso di un CPV (es. "72" o "72267000"); basta un codice della gara che inizi così.
    - `q`: testo cercato (senza distinzione di maiuscole) in titolo, descrizione ed ente.
    - `report_status`: gare il cui report ha quello stato.
    - Ordinamento predefinito: punteggio decrescente, poi scadenza crescente.
    - `page` parte da 1; `page_size` da 1 a `MAX_PAGE_SIZE`.
    """
    if page < 1:
        raise ValueError("page deve essere >= 1")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size deve essere tra 1 e {MAX_PAGE_SIZE}")
    if cpv is not None and not cpv.isdigit():
        raise ValueError("cpv deve contenere solo cifre")

    conditions: list[ColumnElement[bool]] = []
    if min_score is not None:
        conditions.append(Tender.relevance_score >= min_score)
    if is_relevant is not None:
        conditions.append(Tender.is_relevant.is_(is_relevant))
    if cpv:
        # cpv_codes è JSON (ADR-007): testo serializzato `["72000000", ...]`, quindi il
        # prefisso di un codice si cerca come `"<prefisso>`. Vale su PostgreSQL e SQLite.
        conditions.append(cast(Tender.cpv_codes, String).like(f'%"{cpv}%'))
    if deadline_from is not None:
        conditions.append(Tender.submission_deadline >= deadline_from)
    if deadline_to is not None:
        conditions.append(Tender.submission_deadline <= deadline_to)
    if publication_from is not None:
        conditions.append(Tender.publication_date >= publication_from)
    if publication_to is not None:
        conditions.append(Tender.publication_date <= publication_to)
    if min_value is not None:
        conditions.append(Tender.estimated_value >= min_value)
    if max_value is not None:
        conditions.append(Tender.estimated_value <= max_value)
    if report_status is not None:
        conditions.append(
            Tender.id.in_(select(Report.tender_id).where(Report.status == report_status))
        )
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip().lower())}%"
        conditions.append(
            or_(
                func.lower(Tender.title).like(pattern, escape="\\"),
                func.lower(func.coalesce(Tender.description, "")).like(pattern, escape="\\"),
                func.lower(Tender.buyer_name).like(pattern, escape="\\"),
            )
        )

    total = session.scalar(select(func.count()).select_from(Tender).where(*conditions)) or 0
    items = list(
        session.scalars(
            select(Tender)
            .where(*conditions)
            .order_by(*_order_by(sort))
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    )
    return TenderPage(items, total, page, page_size)
