"""Endpoint di scadenze e indicatori della dashboard.

Le date sono calcolate sul giorno corrente in fuso Europe/Rome.
"""

from datetime import date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.api.deps import get_now, get_session
from backend.api.errors import ApiError, error_responses
from backend.api.schemas import YEAR_RANGE, Deadline, DeadlineList, Stats
from backend.api.tenders import tender_from_row
from backend.domain import repository

ROME = ZoneInfo("Europe/Rome")
DEFAULT_RANGE_DAYS = 30
URGENCY_HIGH_DAYS = 3
URGENCY_MEDIUM_DAYS = 7
DEADLINES_PAGE_SIZE = 100
MAX_RANGE_DAYS = 366  # ampiezza massima dell'intervallo di /deadlines

router = APIRouter(tags=["dashboard"])


def urgency_for(days_left: int) -> str:
    """`high` fino a 3 giorni, `medium` fino a 7, `low` oltre (contratto di /deadlines)."""
    if days_left <= URGENCY_HIGH_DAYS:
        return "high"
    if days_left <= URGENCY_MEDIUM_DAYS:
        return "medium"
    return "low"


def _today_rome(now: datetime) -> date:
    return now.astimezone(ROME).date()


@router.get(
    "/deadlines",
    operation_id="listDeadlines",
    summary="Scadenze per il calendario",
    response_model=DeadlineList,
    responses=error_responses(422),
)
def list_deadlines(
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
    from_: Annotated[date | None, Query(alias="from"), YEAR_RANGE] = None,
    to: Annotated[date | None, YEAR_RANGE] = None,
) -> DeadlineList:
    today = _today_rome(now)
    start = from_ or today
    end = to or today + timedelta(days=DEFAULT_RANGE_DAYS)  # come da contratto: oggi + 30
    if end < start:
        raise ApiError(422, "validation_error", "to non può essere prima di from.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise ApiError(
            422,
            "validation_error",
            f"l'intervallo tra from e to non può superare {MAX_RANGE_DAYS} giorni.",
        )

    items: list[Deadline] = []
    page = 1
    while True:
        result = repository.list_tenders(
            session,
            is_relevant=True,
            deadline_from=start,
            deadline_to=end,
            sort="deadline",
            page=page,
            page_size=DEADLINES_PAGE_SIZE,
        )
        for row in result.items:
            tender = tender_from_row(row)
            if tender.submission_deadline is None:  # il filtro esclude chi non ha scadenza
                continue
            # Le scadenze già passate (da `from` nel passato) hanno days_left 0: il contratto non
            # ammette valori negativi.
            days_left = max((tender.submission_deadline.astimezone(ROME).date() - today).days, 0)
            items.append(
                Deadline(
                    tender_id=tender.id,
                    publication_number=tender.publication_number,
                    title=tender.title,
                    buyer_name=tender.buyer_name,
                    submission_deadline=tender.submission_deadline,
                    relevance_score=tender.relevance_score,
                    days_left=days_left,
                    urgency=urgency_for(days_left),  # type: ignore[arg-type]
                )
            )
        if page * DEADLINES_PAGE_SIZE >= result.total or not result.items:
            break
        page += 1
    return DeadlineList(items=items)


@router.get(
    "/stats",
    operation_id="getStats",
    summary="Indicatori della dashboard",
    response_model=Stats,
)
def get_stats(
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_now)],
) -> Stats:
    today = _today_rome(now)
    day_start = datetime.combine(today, time.min, tzinfo=ROME)
    day_end = datetime.combine(today + timedelta(days=1), time.min, tzinfo=ROME)
    return Stats(
        new_tenders_today=repository.count_tenders_created_between(session, day_start, day_end),
        relevant_tenders=repository.list_tenders(session, is_relevant=True, page_size=1).total,
        deadlines_next_7_days=repository.list_tenders(
            session,
            is_relevant=True,
            deadline_from=today,
            deadline_to=today + timedelta(days=URGENCY_MEDIUM_DAYS),
            page_size=1,
        ).total,
        reports_to_verify=repository.list_tenders(
            session, report_status="to_review", include_discarded=True, page_size=1
        ).total,
    )
