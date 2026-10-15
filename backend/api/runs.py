"""Endpoint dello storico e dell'avvio manuale delle esecuzioni (dati di prova in T3.1)."""

from typing import Annotated

from fastapi import APIRouter, Query

from backend.api import sample_data
from backend.api.errors import error_responses
from backend.api.schemas import RunAccepted, RunList

router = APIRouter(tags=["runs"])


@router.get(
    "/runs",
    operation_id="listRuns",
    summary="Storico delle esecuzioni",
    response_model=RunList,
    responses=error_responses(422),
)
def list_runs(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> RunList:
    return RunList(items=sample_data.RUNS[:limit])


@router.post(
    "/runs",
    operation_id="startRun",
    summary="Avvio manuale del monitoraggio",
    status_code=202,
    response_model=RunAccepted,
    responses=error_responses(409),
)
def start_run() -> RunAccepted:
    return RunAccepted(id=sample_data.NEW_RUN_ID, status="running")
