"""Endpoint delle gare e dei loro documenti (dati di prova in T3.1)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.api import sample_data
from backend.api.deps import get_session
from backend.api.errors import ApiError, error_responses
from backend.api.schemas import (
    DocumentList,
    PositiveId,
    ReportStatusFilter,
    Tender,
    TenderList,
)
from backend.domain import repository
from backend.domain.repository import TenderRow

ROME = ZoneInfo("Europe/Rome")
router = APIRouter(tags=["tenders"])


def _aware(value: datetime) -> datetime:
    """SQLite restituisce datetime senza fuso: sono sempre UTC (il repository salva in UTC)."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def tender_from_row(row: TenderRow) -> Tender:
    """Converte una riga del repository nello schema del contratto.

    La scadenza è mostrata in Europe/Rome; `created_at` e `updated_at` restano in UTC.
    """
    tender = row.tender
    data = {name: getattr(tender, name) for name in Tender.model_fields if name != "report_status"}
    if tender.submission_deadline is not None:
        data["submission_deadline"] = _aware(tender.submission_deadline).astimezone(ROME)
    data["created_at"] = _aware(tender.created_at)
    data["updated_at"] = _aware(tender.updated_at)
    return Tender.model_validate({**data, "report_status": row.report_status})


@router.get(
    "/tenders",
    operation_id="listTenders",
    summary="Elenco gare",
    response_model=TenderList,
    responses=error_responses(422),
)
def list_tenders(
    session: Annotated[Session, Depends(get_session)],
    min_score: Annotated[int | None, Query(ge=1, le=5)] = None,
    cpv: Annotated[str | None, Query(pattern=r"^[0-9]{2,8}$")] = None,
    deadline_from: date | None = None,
    deadline_to: date | None = None,
    min_value: Annotated[float | None, Query(ge=0, allow_inf_nan=False)] = None,
    max_value: Annotated[float | None, Query(ge=0, allow_inf_nan=False)] = None,
    report_status: ReportStatusFilter | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    include_discarded: bool = False,
    sort: Literal["relevance", "deadline", "published"] = "relevance",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TenderList:
    # Filtri, ordinamento e paginazione sono del repository: qui solo traduzione dei tipi.
    try:
        result = repository.list_tenders(
            session,
            min_score=min_score,
            cpv=cpv,
            deadline_from=deadline_from,
            deadline_to=deadline_to,
            min_value=None if min_value is None else Decimal(str(min_value)),
            max_value=None if max_value is None else Decimal(str(max_value)),
            report_status=report_status,
            q=q,
            include_discarded=include_discarded,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    return TenderList(
        items=[tender_from_row(row) for row in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get(
    "/tenders/{id}",
    operation_id="getTender",
    summary="Dettaglio di una gara",
    response_model=Tender,
    responses=error_responses(404, 422),
)
def get_tender(id: PositiveId) -> Tender:
    # T3.3: sostituire con repository
    return sample_data.get_sample_tender(id)


@router.get(
    "/tenders/{id}/documents",
    operation_id="listTenderDocuments",
    summary="Documenti della gara",
    response_model=DocumentList,
    responses=error_responses(404, 422),
)
def list_tender_documents(id: PositiveId) -> DocumentList:
    # T3.3: sostituire con repository
    sample_data.get_sample_tender(id)
    return DocumentList(items=[d for d in sample_data.DOCUMENTS if d.tender_id == id])
