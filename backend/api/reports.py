"""Endpoint dei report e della revisione dei campi (dati di prova in T3.1)."""

from fastapi import APIRouter

from backend.api import sample_data
from backend.api.errors import ApiError, error_responses
from backend.api.schemas import FieldReview, PositiveId, Report, ReportCreate

router = APIRouter(tags=["reports"])


@router.get(
    "/tenders/{id}/report",
    operation_id="getTenderReport",
    summary="Report della gara",
    response_model=Report,
    responses=error_responses(404, 422),
)
def get_tender_report(id: PositiveId) -> Report:
    # T3.3: sostituire con repository
    sample_data.get_sample_tender(id)
    if sample_data.REPORT_101.tender_id != id:
        raise ApiError(404, "report_not_found", f"La gara {id} non ha ancora un report.")
    return sample_data.REPORT_101


@router.post(
    "/tenders/{id}/report",
    operation_id="createTenderReport",
    summary="Caricamento del report prodotto dalla Skill",
    status_code=201,
    response_model=Report,
    responses=error_responses(404, 409, 422),
)
def create_tender_report(id: PositiveId, body: ReportCreate) -> Report:
    # T3.3: sostituire con repository (validazione con lo schema di T2.5)
    sample_data.get_sample_tender(id)
    if sample_data.REPORT_101.tender_id == id:
        raise ApiError(409, "report_already_exists", f"La gara {id} ha già un report.")
    return sample_data.REPORT_CREATED


@router.patch(
    "/reports/{id}/fields/{field_id}",
    operation_id="reviewReportField",
    summary="Conferma o correzione di un campo da parte del revisore",
    response_model=Report,
    responses=error_responses(404, 422),
)
def review_report_field(id: PositiveId, field_id: PositiveId, body: FieldReview) -> Report:
    # T3.4: sostituire con repository e ricalcolo dello stato del report
    report = sample_data.REPORT_101
    if id != report.id:
        raise ApiError(404, "report_not_found", f"Il report {id} non esiste.")
    if all(f.id != field_id for f in report.fields):
        raise ApiError(
            404, "field_not_found", f"Il campo {field_id} non appartiene al report {id}."
        )
    return report
