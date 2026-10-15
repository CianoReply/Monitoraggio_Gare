"""Endpoint dei report e della revisione dei campi."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.api.convert import aware
from backend.api.deps import get_session
from backend.api.errors import ApiError, error_responses
from backend.api.schemas import PositiveId, Report, contains_nul
from backend.api.schemas import ReportField as ReportFieldSchema
from backend.domain import reports as domain_reports
from backend.domain.models import Report as ReportModel
from backend.domain.models import ReportField as ReportFieldModel
from backend.domain.reports import FieldReview, ReportCreate

router = APIRouter(tags=["reports"])


def _reject_nul(body: BaseModel) -> None:
    """NUL nei testi non è ammesso: PostgreSQL lo rifiuta e darebbe un 500."""
    if contains_nul(body.model_dump(mode="json")):
        raise ApiError(422, "validation_error", "body: contiene caratteri non validi (NUL)")


def _field_from_model(field: ReportFieldModel) -> ReportFieldSchema:
    return ReportFieldSchema(
        id=field.id,
        report_id=field.report_id,
        label=field.label,
        value=field.value,
        original_value=field.original_value,
        source_doc=field.source_doc,
        source_page=field.source_page,
        is_critical=field.is_critical,
        verification_status=field.verification_status.value,
        reviewer=field.reviewer,
        reviewed_at=aware(field.reviewed_at) if field.reviewed_at else None,
    )


def report_from_model(report: ReportModel) -> Report:
    """Converte il report del dominio nello schema del contratto (datetime sempre con fuso)."""
    return Report(
        id=report.id,
        tender_id=report.tender_id,
        summary=report.summary,
        status=report.status.value,
        generated_at=aware(report.generated_at),
        ai_label=report.ai_label,
        fields=[_field_from_model(f) for f in report.fields],
    )


@router.get(
    "/tenders/{id}/report",
    operation_id="getTenderReport",
    summary="Report della gara",
    response_model=Report,
    responses=error_responses(404, 422),
)
def get_tender_report(id: PositiveId, session: Annotated[Session, Depends(get_session)]) -> Report:
    return report_from_model(domain_reports.get_report_for_tender(session, id))


@router.post(
    "/tenders/{id}/report",
    operation_id="createTenderReport",
    summary="Caricamento del report prodotto dalla Skill",
    status_code=201,
    response_model=Report,
    responses=error_responses(404, 409, 422),
)
def create_tender_report(
    id: PositiveId, body: ReportCreate, session: Annotated[Session, Depends(get_session)]
) -> Report:
    # Validazione e regole (un solo report per gara) sono del dominio; qui solo la transazione:
    # il dominio fa flush, il commit spetta all'API. Il corpo è il modello del dominio (stretto).
    _reject_nul(body)
    report = domain_reports.create_report(session, id, body)
    session.commit()
    return report_from_model(report)


@router.patch(
    "/reports/{id}/fields/{field_id}",
    operation_id="reviewReportField",
    summary="Conferma o correzione di un campo da parte del revisore",
    response_model=Report,
    responses=error_responses(404, 422),
)
def review_report_field(
    id: PositiveId,
    field_id: PositiveId,
    body: FieldReview,
    session: Annotated[Session, Depends(get_session)],
) -> Report:
    # Regole di revisione (stato dei campi, original_value, ricalcolo dello stato del report e
    # dell'etichetta) sono del dominio; qui solo la transazione.
    _reject_nul(body)
    report = domain_reports.review_field(session, id, field_id, body)
    session.commit()
    return report_from_model(report)
