"""Endpoint delle gare e dei loro documenti (dati di prova in T3.1)."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from backend.api import sample_data
from backend.api.errors import ApiError, error_responses
from backend.api.schemas import DocumentList, ReportStatusFilter, Tender, TenderList

router = APIRouter(tags=["tenders"])


def get_sample_tender(tender_id: int) -> Tender:
    """Restituisce la gara di prova o solleva `tender_not_found`."""
    for tender in sample_data.TENDERS:
        if tender.id == tender_id:
            return tender
    raise ApiError(404, "tender_not_found", f"La gara {tender_id} non esiste.")


@router.get(
    "/tenders",
    operation_id="listTenders",
    summary="Elenco gare",
    response_model=TenderList,
    responses=error_responses(422),
)
def list_tenders(
    min_score: Annotated[int | None, Query(ge=1, le=5)] = None,
    cpv: Annotated[str | None, Query(pattern=r"^[0-9]{2,8}$")] = None,
    deadline_from: date | None = None,
    deadline_to: date | None = None,
    min_value: Annotated[float | None, Query(ge=0)] = None,
    max_value: Annotated[float | None, Query(ge=0)] = None,
    report_status: ReportStatusFilter | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    include_discarded: bool = False,
    sort: Literal["relevance", "deadline", "published"] = "relevance",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TenderList:
    if deadline_from and deadline_to and deadline_from > deadline_to:
        raise ApiError(422, "validation_error", "deadline_from non può essere dopo deadline_to.")
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ApiError(422, "validation_error", "min_value non può essere maggiore di max_value.")
    items = sample_data.TENDERS
    return TenderList(items=items, total=len(items), page=page, page_size=page_size)


@router.get(
    "/tenders/{id}",
    operation_id="getTender",
    summary="Dettaglio di una gara",
    response_model=Tender,
    responses=error_responses(404, 422),
)
def get_tender(id: int) -> Tender:
    return get_sample_tender(id)


@router.get(
    "/tenders/{id}/documents",
    operation_id="listTenderDocuments",
    summary="Documenti della gara",
    response_model=DocumentList,
    responses=error_responses(404, 422),
)
def list_tender_documents(id: int) -> DocumentList:
    get_sample_tender(id)
    return DocumentList(items=[d for d in sample_data.DOCUMENTS if d.tender_id == id])
