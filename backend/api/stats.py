"""Endpoint di scadenze e indicatori della dashboard (dati di prova in T3.1)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from backend.api import sample_data
from backend.api.errors import ApiError, error_responses
from backend.api.schemas import DeadlineList, Stats

router = APIRouter(tags=["dashboard"])


@router.get(
    "/deadlines",
    operation_id="listDeadlines",
    summary="Scadenze per il calendario",
    response_model=DeadlineList,
    responses=error_responses(422),
)
def list_deadlines(
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
) -> DeadlineList:
    if from_ and to and to < from_:
        raise ApiError(422, "validation_error", "to non può essere prima di from.")
    return DeadlineList(items=sample_data.DEADLINES)


@router.get("/stats", operation_id="getStats", summary="Indicatori della dashboard")
def get_stats() -> Stats:
    return sample_data.STATS
