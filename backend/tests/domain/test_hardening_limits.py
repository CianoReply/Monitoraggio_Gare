"""Limiti che il database rifiuterebbe (PostgreSQL): valori fuori intervallo, NUL, date estreme."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.domain.reports import (
    MAX_SOURCE_PAGE,
    ReportValidationError,
    create_report,
    review_field,
)
from backend.domain.repository import (
    MAX_OFFSET,
    InvalidQueryError,
    list_runs,
    list_tenders,
)
from backend.domain.schemas import NUL, TenderEvaluation
from backend.tests.domain.conftest import make_tender
from backend.tests.domain.test_reports import VALID_REPORT, add_tender, report_payload, with_field

# --- TenderCreate ---


def test_estimated_value_must_fit_numeric_18_2() -> None:
    assert make_tender(estimated_value=Decimal("9999999999999999.99")).estimated_value
    for bad in (Decimal(10) ** 16, Decimal("1e20"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValidationError):
            make_tender(estimated_value=bad)


@pytest.mark.parametrize(
    "field",
    [
        "publication_number",
        "title",
        "description",
        "buyer_name",
        "buyer_city",
        "notice_type",
        "currency",
        "ted_url",
        "documents_url",
        "parent_publication_number",
    ],
)
def test_tender_text_fields_reject_nul(field: str) -> None:
    value = "EUR" if field == "currency" else f"abc{NUL}def"
    if field == "currency":
        value = f"E{NUL}R"
    with pytest.raises(ValidationError, match="NUL"):
        make_tender(**{field: value})


def test_tender_without_nul_is_still_valid() -> None:
    assert make_tender(description="testo normale").description == "testo normale"


def test_discard_reason_must_fit_the_column_and_have_no_nul() -> None:
    TenderEvaluation(1, False, "x" * 500)
    with pytest.raises(ValueError, match="discard_reason"):
        TenderEvaluation(1, False, "x" * 501)
    with pytest.raises(ValueError, match="discard_reason"):
        TenderEvaluation(1, False, f"a{NUL}b")


# --- Report ---


def _fields_with(**changes: Any) -> dict[str, Any]:
    return with_field(**changes)


@pytest.mark.parametrize(
    ("payload", "where"),
    [
        (report_payload(summary=f"a{NUL}b"), "summary"),
        (_fields_with(label=f"a{NUL}b"), "fields.0.label"),
        (_fields_with(value=f"a{NUL}b"), "fields.0.value"),
        (_fields_with(source_doc=f"a{NUL}b"), "fields.0.source_doc"),
        (_fields_with(source_page=MAX_SOURCE_PAGE + 1), "fields.0.source_page"),
    ],
)
def test_report_rejects_nul_and_oversized_page(
    session: Session, payload: dict[str, Any], where: str
) -> None:
    tender = add_tender(session)
    with pytest.raises(ReportValidationError) as excinfo:
        create_report(session, tender.id, payload)
    assert any(error.startswith(where) for error in excinfo.value.errors)
    assert excinfo.value.code == "validation_error"


def test_report_accepts_the_maximum_page(session: Session) -> None:
    tender = add_tender(session)
    report = create_report(session, tender.id, _fields_with(source_page=MAX_SOURCE_PAGE))
    assert report.fields[0].source_page == MAX_SOURCE_PAGE


def test_review_rejects_nul_in_reviewer_and_value(session: Session) -> None:
    tender = add_tender(session)
    report = create_report(session, tender.id, VALID_REPORT)
    field_id = report.fields[0].id
    with pytest.raises(ReportValidationError, match="reviewer: non può contenere"):
        review_field(session, report.id, field_id, {"action": "confirm", "reviewer": f"A{NUL}"})
    with pytest.raises(ReportValidationError, match="value: non può contenere"):
        review_field(
            session, report.id, field_id, {"action": "correct", "value": f"x{NUL}", "reviewer": "A"}
        )
    assert report.fields[0].reviewer is None


# --- list_tenders ---


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_score": 9},
        {"cpv": "x"},
        {"min_value": Decimal(-1)},
        {"min_value": Decimal(5), "max_value": Decimal(1)},
        {"deadline_from": date(2026, 2, 1), "deadline_to": date(2026, 1, 1)},
        {"report_status": "boh"},
        {"q": "x" * 201},
        {"q": f"a{NUL}b"},
        {"page": 0},
        {"page_size": 101},
        {"sort": "value_desc"},
    ],
)
def test_invalid_parameters_raise_the_dedicated_error(
    session: Session, kwargs: dict[str, Any]
) -> None:
    with pytest.raises(InvalidQueryError) as excinfo:
        list_tenders(session, **kwargs)
    assert isinstance(excinfo.value, ValueError)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"deadline_from": date.min},
        {"deadline_to": date.max},
        {"deadline_from": date.max, "deadline_to": date.max},
        {"deadline_from": date.min, "deadline_to": date.min},
        {"deadline_to": date.min},
    ],
)
def test_extreme_dates_are_a_clear_error_not_an_overflow(
    session: Session, kwargs: dict[str, Any]
) -> None:
    try:
        list_tenders(session, **kwargs)
    except InvalidQueryError as exc:
        assert "intervallo supportato" in str(exc)
    else:  # una data estrema ma rappresentabile è semplicemente un filtro che non trova nulla
        pass


def test_dates_at_the_edges_that_overflow_are_rejected(session: Session) -> None:
    with pytest.raises(InvalidQueryError, match="intervallo supportato"):
        list_tenders(session, deadline_to=date.max)
    with pytest.raises(InvalidQueryError, match="intervallo supportato"):
        list_tenders(session, deadline_from=date.min)


def test_huge_page_is_rejected_before_reaching_the_database(session: Session) -> None:
    with pytest.raises(InvalidQueryError, match="page troppo grande"):
        list_tenders(session, page=10**20)
    with pytest.raises(InvalidQueryError, match="page troppo grande"):
        list_tenders(session, page=MAX_OFFSET, page_size=100)
    assert list_tenders(session, page=1000, page_size=100).items == []


def test_list_runs_invalid_limit_uses_the_dedicated_error(session: Session) -> None:
    with pytest.raises(InvalidQueryError):
        list_runs(session, limit=0)
