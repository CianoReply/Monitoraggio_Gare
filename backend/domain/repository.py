"""Accesso ai dati: unico punto da cui gli altri moduli leggono e scrivono le gare.

Le funzioni usano la `Session` ricevuta e fanno solo `flush`: il `commit` spetta a chi
possiede la transazione (job di ingestion, endpoint API).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Literal, NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from backend.domain.models import Report, Tender, utcnow
from backend.domain.schemas import TenderCreate, TenderEvaluation

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_QUERY_LENGTH = 200
ROME = ZoneInfo("Europe/Rome")

# Valori di `sort` del contratto API (docs/API_CONTRACT.yaml).
SortKey = Literal["relevance", "deadline", "published"]
# Stato del report derivato: `none` se la gara non ha report (ADR-012).
ReportStatusFilter = Literal["none", "to_review", "verified"]


class UpsertResult(NamedTuple):
    tender: Tender
    created: bool


class TenderRow(NamedTuple):
    """Una gara dell'elenco con lo stato derivato del suo report (senza query per gara)."""

    tender: Tender
    report_status: ReportStatusFilter


class TenderPage(NamedTuple):
    items: list[TenderRow]
    total: int
    page: int
    page_size: int


def upsert_tender(
    session: Session, data: TenderCreate, evaluation: TenderEvaluation
) -> UpsertResult:
    """Inserisce la gara o, se `publication_number` esiste già, la aggiorna.

    La gara si salva già valutata (ADR-010): `evaluation` (punteggio, rilevanza, motivo di
    scarto) viene scritto sia in inserimento sia in aggiornamento. La scadenza è salvata in UTC.
    Restituisce la gara e `created=True` se è nuova.
    """
    values = data.model_dump()
    if data.submission_deadline is not None:
        values["submission_deadline"] = data.submission_deadline.astimezone(UTC)
    values.update(
        relevance_score=evaluation.relevance_score,
        is_relevant=evaluation.is_relevant,
        discard_reason=evaluation.discard_reason,
    )
    tender = get_tender_by_publication_number(session, data.publication_number)
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


def _day_start_utc(day: date) -> datetime:
    """Mezzanotte del giorno in Europe/Rome, espressa in UTC."""
    return datetime.combine(day, time.min, tzinfo=ROME).astimezone(UTC)


def _order_by(sort: SortKey) -> list[ColumnElement]:
    """Ordinamento con le gare senza scadenza sempre in fondo (uguale su PostgreSQL e SQLite)."""
    deadline_asc = [Tender.submission_deadline.is_(None), Tender.submission_deadline.asc()]
    if sort == "relevance":
        order = [Tender.relevance_score.desc(), *deadline_asc]
    elif sort == "deadline":
        order = deadline_asc
    elif sort == "published":
        order = [Tender.publication_date.desc(), *deadline_asc]
    else:
        raise ValueError(f"sort non valido: {sort!r}")
    return [*order, Tender.id.asc()]


def list_tenders(
    session: Session,
    *,
    min_score: int | None = None,
    cpv: str | None = None,
    deadline_from: date | None = None,
    deadline_to: date | None = None,
    min_value: Decimal | None = None,
    max_value: Decimal | None = None,
    report_status: ReportStatusFilter | None = None,
    q: str | None = None,
    include_discarded: bool = False,
    sort: SortKey = "relevance",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    is_relevant: bool | None = None,
    publication_from: date | None = None,
    publication_to: date | None = None,
) -> TenderPage:
    """Elenco paginato di gare con filtri in AND, come `GET /tenders` del contratto API.

    - `cpv`: prefisso di 2-8 cifre; basta un CPV della gara che inizi così.
    - `deadline_from`/`deadline_to`: giorni inclusivi in Europe/Rome, cioè
      scadenza in [da 00:00, a+1 00:00). Le gare senza scadenza sono escluse se il filtro c'è.
    - `min_value`/`max_value`: le gare senza importo sono escluse se il filtro c'è.
    - `report_status`: `none` / `to_review` / `verified` (ADR-012).
    - `q`: testo cercato (senza distinzione di maiuscole) in titolo, descrizione ed ente; max 200.
    - `include_discarded`: se `False` esclude le gare con `discard_reason` (ADR-012).
    - `page` da 1; `page_size` da 1 a 100.
    - `is_relevant`, `publication_from`, `publication_to`: NON fanno parte di `GET /tenders`;
      uso interno (`/deadlines`, `/stats`).
    Parametri non validi o intervalli invertiti sollevano `ValueError`.
    """
    if min_score is not None and not 1 <= min_score <= 5:
        raise ValueError("min_score deve essere tra 1 e 5")
    if cpv is not None and not re.fullmatch(r"\d{2,8}", cpv):
        raise ValueError("cpv deve essere un prefisso di 2-8 cifre")
    if (min_value is not None and min_value < 0) or (max_value is not None and max_value < 0):
        raise ValueError("min_value e max_value devono essere >= 0")
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValueError("min_value non può superare max_value")
    if deadline_from is not None and deadline_to is not None and deadline_from > deadline_to:
        raise ValueError("deadline_from non può superare deadline_to")
    if report_status is not None and report_status not in ("none", "to_review", "verified"):
        raise ValueError(f"report_status non valido: {report_status!r}")
    if q is not None and len(q) > MAX_QUERY_LENGTH:
        raise ValueError(f"q non può superare {MAX_QUERY_LENGTH} caratteri")
    if page < 1:
        raise ValueError("page deve essere >= 1")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size deve essere tra 1 e {MAX_PAGE_SIZE}")

    # Stato del report calcolato nella stessa query (LEFT JOIN: al massimo un report per gara).
    status_col = func.coalesce(cast(Report.status, String), "none")
    conditions: list[ColumnElement[bool]] = []
    if not include_discarded:
        conditions.append(Tender.discard_reason.is_(None))
    if min_score is not None:
        conditions.append(Tender.relevance_score >= min_score)
    if is_relevant is not None:
        conditions.append(Tender.is_relevant.is_(is_relevant))
    if cpv:
        # cpv_codes è JSON (ADR-007): testo serializzato `["72000000", ...]`, quindi il
        # prefisso di un codice si cerca come `"<prefisso>`. Vale su PostgreSQL e SQLite.
        conditions.append(cast(Tender.cpv_codes, String).like(f'%"{cpv}%'))
    if deadline_from is not None:
        conditions.append(Tender.submission_deadline >= _day_start_utc(deadline_from))
    if deadline_to is not None:
        conditions.append(Tender.submission_deadline < _day_start_utc(deadline_to + timedelta(1)))
    if publication_from is not None:
        conditions.append(Tender.publication_date >= publication_from)
    if publication_to is not None:
        conditions.append(Tender.publication_date <= publication_to)
    if min_value is not None:
        conditions.append(Tender.estimated_value >= min_value)
    if max_value is not None:
        conditions.append(Tender.estimated_value <= max_value)
    if report_status is not None:
        conditions.append(status_col == report_status)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip().lower())}%"
        conditions.append(
            or_(
                func.lower(Tender.title).like(pattern, escape="\\"),
                func.lower(func.coalesce(Tender.description, "")).like(pattern, escape="\\"),
                func.lower(Tender.buyer_name).like(pattern, escape="\\"),
            )
        )

    total = (
        session.scalar(
            select(func.count())
            .select_from(Tender)
            .outerjoin(Report, Report.tender_id == Tender.id)
            .where(*conditions)
        )
        or 0
    )
    rows = session.execute(
        select(Tender, status_col)
        .outerjoin(Report, Report.tender_id == Tender.id)
        .where(*conditions)
        .order_by(*_order_by(sort))
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    items = [TenderRow(tender, status) for tender, status in rows]
    return TenderPage(items, total, page, page_size)
