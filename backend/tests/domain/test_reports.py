"""Test dell'archiviazione dei report (T2.5): schema, creazione, revisione dei campi, errori."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.domain.models import ReportStatus, Tender, VerificationStatus
from backend.domain.reports import (
    LABEL_TO_REVIEW,
    FieldNotFoundError,
    FieldReview,
    ReportAlreadyExistsError,
    ReportCreate,
    ReportError,
    ReportNotFoundError,
    ReportValidationError,
    TenderNotFoundError,
    compute_report_status,
    create_report,
    get_report,
    get_report_for_tender,
    label_verified,
    load_report_schema,
    review_field,
    validate_field_review,
    validate_report,
)
from backend.domain.repository import reset_report_to_review, upsert_tender
from backend.domain.schemas import TenderEvaluation
from backend.tests.contract_utils import resolve
from backend.tests.domain.conftest import make_tender

NOW = datetime(2026, 10, 15, 8, 30, tzinfo=UTC)

VALID_REPORT: dict[str, Any] = {
    "summary": "Accordo quadro triennale per sviluppo e manutenzione evolutiva.",
    "generated_at": "2026-10-14T09:15:00+00:00",
    "fields": [
        {
            "label": "Importo a base di gara",
            "value": "2.400.000 EUR",
            "source_doc": "Disciplinare.pdf",
            "source_page": 3,
            "is_critical": True,
        },
        {
            "label": "Fatturato minimo",
            "value": "1.000.000 EUR",
            "source_doc": "Disciplinare.pdf",
            "source_page": None,
            "is_critical": True,
        },
        {
            "label": "Criterio di aggiudicazione",
            "value": "Offerta economicamente più vantaggiosa",
            "source_doc": "Bando.pdf",
            "is_critical": False,
        },
    ],
}


def report_payload(**overrides: Any) -> dict[str, Any]:
    payload = deepcopy(VALID_REPORT)
    payload.update(overrides)
    return payload


def add_tender(session: Session, number: str = "000001-2026") -> Tender:
    tender, _ = upsert_tender(
        session, make_tender(publication_number=number), TenderEvaluation(4, True)
    )
    return tender


@pytest.fixture
def tender(session: Session) -> Tender:
    return add_tender(session)


# --- Schema ---


def _without_descriptions(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _without_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [_without_descriptions(v) for v in node]
    return node


@pytest.mark.parametrize("name", ["ReportCreate", "FieldReview"])
def test_report_schema_matches_api_contract(spec: dict, name: str) -> None:
    contract = _without_descriptions(resolve(spec, spec["components"]["schemas"][name]))
    ours = _without_descriptions(load_report_schema()["definitions"][name])
    assert ours == contract


def test_report_schema_root_is_report_create() -> None:
    schema = load_report_schema()
    assert schema["$ref"] == "#/definitions/ReportCreate"


def with_field(**changes: Any) -> dict[str, Any]:
    """Report valido con il primo campo modificato (una chiave a None viene tolta)."""
    field = {**VALID_REPORT["fields"][0], **changes}
    field = {k: v for k, v in field.items() if v != "__remove__"}
    return report_payload(fields=[field])


MINIMAL_FIELD = {"label": "l", "value": "v", "source_doc": "d", "is_critical": False}

REPORT_CASES: list[tuple[str, Any]] = [
    ("valid", VALID_REPORT),
    ("minimal", {"summary": "s", "fields": [MINIMAL_FIELD]}),
    ("no summary", {"fields": VALID_REPORT["fields"]}),
    ("empty summary", report_payload(summary="")),
    ("summary not string", report_payload(summary=5)),
    ("no fields", {"summary": "s"}),
    ("empty fields", report_payload(fields=[])),
    ("fields not list", report_payload(fields="x")),
    ("extra top-level key", report_payload(extra=1)),
    ("field extra key", with_field(x=1)),
    ("field without label", with_field(label="__remove__")),
    ("field empty value", with_field(value="")),
    ("field empty source_doc", with_field(source_doc="")),
    ("field page 0", with_field(source_page=0)),
    ("field page string", with_field(source_page="3")),
    ("field page bool", with_field(source_page=True)),
    ("field is_critical string", with_field(is_critical="si")),
    ("field is_critical missing", with_field(is_critical="__remove__")),
    ("field not object", report_payload(fields=["x"])),
    ("not an object", ["x"]),
]

REVIEW_CASES: list[tuple[str, Any]] = [
    ("confirm", {"action": "confirm", "reviewer": "Giuseppe Rossi"}),
    ("confirm with value", {"action": "confirm", "value": "x", "reviewer": "G"}),
    ("correct", {"action": "correct", "value": "2.450.000 EUR", "reviewer": "G"}),
    ("correct without value", {"action": "correct", "reviewer": "G"}),
    ("correct empty value", {"action": "correct", "value": "", "reviewer": "G"}),
    ("unknown action", {"action": "delete", "reviewer": "G"}),
    ("no action", {"reviewer": "G"}),
    ("no reviewer", {"action": "confirm"}),
    ("empty reviewer", {"action": "confirm", "reviewer": ""}),
    ("extra key", {"action": "confirm", "reviewer": "G", "x": 1}),
    ("reviewer not string", {"action": "confirm", "reviewer": 3}),
]


@pytest.mark.parametrize(("name", "payload"), REPORT_CASES, ids=[n for n, _ in REPORT_CASES])
def test_pydantic_report_validation_agrees_with_json_schema(name: str, payload: Any) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = load_report_schema()
    validator = jsonschema.Draft202012Validator(schema)
    expected_valid = validator.is_valid(payload)
    try:
        validate_report(payload)
        actual_valid = True
    except ReportValidationError:
        actual_valid = False
    assert actual_valid == expected_valid, name


@pytest.mark.parametrize(("name", "payload"), REVIEW_CASES, ids=[n for n, _ in REVIEW_CASES])
def test_pydantic_review_validation_agrees_with_json_schema(name: str, payload: Any) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = {
        "$schema": load_report_schema()["$schema"],
        "$ref": "#/definitions/FieldReview",
        "definitions": load_report_schema()["definitions"],
    }
    expected_valid = jsonschema.Draft202012Validator(schema).is_valid(payload)
    try:
        validate_field_review(payload)
        actual_valid = True
    except ReportValidationError:
        actual_valid = False
    assert actual_valid == expected_valid, name


# --- Validazione e messaggi ---


def test_validate_report_accepts_dict_and_model() -> None:
    parsed = validate_report(VALID_REPORT)
    assert isinstance(parsed, ReportCreate)
    assert parsed.fields[1].source_page is None and parsed.fields[2].source_page is None
    assert validate_report(parsed) is parsed


def test_invalid_report_error_is_clear_and_lists_every_problem() -> None:
    bad = report_payload(
        summary="",
        fields=[{"label": "", "value": "v", "source_doc": "d", "is_critical": "si", "x": 1}],
    )
    with pytest.raises(ReportValidationError) as excinfo:
        validate_report(bad)
    error = excinfo.value
    assert error.code == "validation_error"
    assert isinstance(error, ValueError) and isinstance(error, ReportError)
    text = str(error)
    assert text.startswith("Report non valido: ")
    assert "summary: non può essere vuoto" in text
    assert "fields.0.label: non può essere vuoto" in text
    assert "fields.0.is_critical: deve essere vero o falso" in text
    assert "fields.0.x: campo non previsto" in text
    assert len(error.errors) == 4


def test_missing_and_empty_fields_messages() -> None:
    with pytest.raises(ReportValidationError, match="summary: campo obbligatorio"):
        validate_report({"fields": VALID_REPORT["fields"]})
    with pytest.raises(ReportValidationError, match="fields: deve contenere almeno un elemento"):
        validate_report(report_payload(fields=[]))
    with pytest.raises(ReportValidationError, match="fields.0.source_page"):
        validate_report(report_payload(fields=[{**VALID_REPORT["fields"][0], "source_page": 0}]))
    with pytest.raises(ReportValidationError, match="Report non valido"):
        validate_report("non un oggetto")  # type: ignore[arg-type]


def test_naive_generated_at_is_rejected() -> None:
    with pytest.raises(ReportValidationError, match="generated_at"):
        validate_report(report_payload(generated_at="2026-10-14T09:15:00"))


def test_invalid_review_messages() -> None:
    with pytest.raises(ReportValidationError, match="value è obbligatorio"):
        validate_field_review({"action": "correct", "reviewer": "G"})
    with pytest.raises(ReportValidationError, match="action: valore non ammesso"):
        validate_field_review({"action": "delete", "reviewer": "G"})
    with pytest.raises(ReportValidationError, match="reviewer: campo obbligatorio"):
        validate_field_review({"action": "confirm"})
    review = FieldReview(action="confirm", reviewer="G")
    assert validate_field_review(review) is review


# --- Creazione ---


def test_create_report_stores_to_review_report_with_unverified_fields(
    session: Session, tender: Tender
) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    assert report.id is not None and report.tender_id == tender.id
    assert report.status == ReportStatus.TO_REVIEW
    assert report.ai_label == LABEL_TO_REVIEW == "Contenuto generato con IA – da revisionare"
    assert report.generated_at == datetime(2026, 10, 14, 9, 15, tzinfo=UTC)
    assert [f.label for f in report.fields] == [f["label"] for f in VALID_REPORT["fields"]]
    assert all(f.verification_status == VerificationStatus.TO_VERIFY for f in report.fields)
    assert [f.is_critical for f in report.fields] == [True, True, False]
    assert all(f.original_value is None and f.reviewer is None for f in report.fields)
    assert [f.source_page for f in report.fields] == [3, None, None]


def test_generated_at_defaults_to_given_now_or_current_time(session: Session) -> None:
    payload = {k: v for k, v in VALID_REPORT.items() if k != "generated_at"}
    first = create_report(session, add_tender(session, "a").id, payload, now=NOW)
    assert first.generated_at == NOW
    second = create_report(session, add_tender(session, "b").id, payload)
    assert abs((datetime.now(UTC) - second.generated_at.replace(tzinfo=UTC)).total_seconds()) < 5


def test_create_report_accepts_a_validated_model(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, ReportCreate.model_validate(VALID_REPORT))
    assert len(report.fields) == 3


def test_invalid_report_is_rejected_and_nothing_is_saved(session: Session, tender: Tender) -> None:
    with pytest.raises(ReportValidationError):
        create_report(session, tender.id, report_payload(fields=[]))
    with pytest.raises(ReportNotFoundError):
        get_report_for_tender(session, tender.id)


def test_second_report_for_same_tender_is_a_conflict(session: Session, tender: Tender) -> None:
    create_report(session, tender.id, VALID_REPORT)
    with pytest.raises(ReportAlreadyExistsError) as excinfo:
        create_report(session, tender.id, VALID_REPORT)
    assert excinfo.value.code == "report_already_exists"
    assert str(excinfo.value) == f"La gara {tender.id} ha già un report."
    assert excinfo.value.message == str(excinfo.value)


def test_create_report_for_missing_tender(session: Session) -> None:
    with pytest.raises(TenderNotFoundError) as excinfo:
        create_report(session, 9999, VALID_REPORT)
    assert excinfo.value.code == "tender_not_found"


def test_validation_is_checked_before_tender_existence(session: Session) -> None:
    with pytest.raises(ReportValidationError):
        create_report(session, 9999, {"summary": ""})


# --- Lettura ---


def test_get_report_for_tender_and_by_id(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    assert get_report_for_tender(session, tender.id) is report
    assert get_report(session, report.id) is report


def test_get_report_errors(session: Session, tender: Tender) -> None:
    with pytest.raises(ReportNotFoundError) as no_report:
        get_report_for_tender(session, tender.id)
    assert no_report.value.code == "report_not_found"
    assert str(no_report.value) == f"La gara {tender.id} non ha ancora un report."
    with pytest.raises(TenderNotFoundError):
        get_report_for_tender(session, 9999)
    with pytest.raises(ReportNotFoundError, match="Il report 77 non esiste"):
        get_report(session, 77)


# --- Revisione ---


def field_by_label(report: Any, label: str) -> Any:
    return next(f for f in report.fields if f.label == label)


def test_confirm_marks_field_verified_with_reviewer_and_time(
    session: Session, tender: Tender
) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    field = field_by_label(report, "Importo a base di gara")
    result = review_field(
        session, report.id, field.id, {"action": "confirm", "reviewer": "Giuseppe Rossi"}, now=NOW
    )
    assert result is report
    assert field.verification_status == VerificationStatus.VERIFIED
    assert (field.reviewer, field.reviewed_at) == ("Giuseppe Rossi", NOW)
    assert field.value == "2.400.000 EUR" and field.original_value is None
    assert report.status == ReportStatus.TO_REVIEW  # manca l'altro campo critico
    assert report.ai_label == LABEL_TO_REVIEW


def test_report_is_verified_only_when_all_critical_fields_are_confirmed(
    session: Session, tender: Tender
) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    amount = field_by_label(report, "Importo a base di gara")
    turnover = field_by_label(report, "Fatturato minimo")
    optional = field_by_label(report, "Criterio di aggiudicazione")

    review_field(session, report.id, amount.id, {"action": "confirm", "reviewer": "Anna"}, NOW)
    assert report.status == ReportStatus.TO_REVIEW
    review_field(session, report.id, optional.id, {"action": "confirm", "reviewer": "Bruno"}, NOW)
    assert report.status == ReportStatus.TO_REVIEW  # un campo non critico non basta
    assert compute_report_status(report) == ReportStatus.TO_REVIEW
    review_field(session, report.id, turnover.id, {"action": "confirm", "reviewer": "Carla"}, NOW)
    assert report.status == ReportStatus.VERIFIED
    assert compute_report_status(report) == ReportStatus.VERIFIED


def test_non_critical_field_left_unverified_does_not_block_verification(
    session: Session, tender: Tender
) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    for label in ("Importo a base di gara", "Fatturato minimo"):
        review_field(
            session,
            report.id,
            field_by_label(report, label).id,
            {"action": "confirm", "reviewer": "Anna"},
            NOW,
        )
    optional = field_by_label(report, "Criterio di aggiudicazione")
    assert optional.verification_status == VerificationStatus.TO_VERIFY
    assert report.status == ReportStatus.VERIFIED


def test_ai_label_is_updated_with_last_reviewer_and_date(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    first = field_by_label(report, "Importo a base di gara")
    second = field_by_label(report, "Fatturato minimo")
    review_field(session, report.id, first.id, {"action": "confirm", "reviewer": "Anna"}, NOW)
    later = NOW + timedelta(days=1)
    review_field(session, report.id, second.id, {"action": "confirm", "reviewer": "Bruno"}, later)
    assert report.ai_label == "Contenuto generato con IA – revisionato da Bruno, 2026-10-16"
    assert report.ai_label == label_verified("Bruno", later.date())
    # una nuova revisione su un report già verificato aggiorna revisore e data
    even_later = NOW + timedelta(days=2)
    review_field(
        session,
        report.id,
        first.id,
        {"action": "correct", "value": "9", "reviewer": "Carla"},
        even_later,
    )
    assert report.status == ReportStatus.VERIFIED
    assert report.ai_label == "Contenuto generato con IA – revisionato da Carla, 2026-10-17"


def test_correct_replaces_value_and_keeps_original_only_first_time(
    session: Session, tender: Tender
) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    field = field_by_label(report, "Importo a base di gara")
    review_field(
        session,
        report.id,
        field.id,
        {"action": "correct", "value": "2.450.000 EUR", "reviewer": "Anna"},
        NOW,
    )
    assert (field.value, field.original_value) == ("2.450.000 EUR", "2.400.000 EUR")
    assert field.verification_status == VerificationStatus.VERIFIED
    review_field(
        session,
        report.id,
        field.id,
        {"action": "correct", "value": "2.500.000 EUR", "reviewer": "Bruno"},
        NOW,
    )
    assert (field.value, field.original_value) == ("2.500.000 EUR", "2.400.000 EUR")
    assert field.reviewer == "Bruno"
    review_field(session, report.id, field.id, {"action": "confirm", "reviewer": "Carla"}, NOW)
    assert (field.value, field.original_value) == ("2.500.000 EUR", "2.400.000 EUR")


def test_confirm_ignores_a_value_sent_with_it(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    field = field_by_label(report, "Importo a base di gara")
    review_field(
        session, report.id, field.id, {"action": "confirm", "value": "altro", "reviewer": "A"}, NOW
    )
    assert field.value == "2.400.000 EUR" and field.original_value is None


def test_review_accepts_a_validated_model(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    field = report.fields[0]
    review_field(session, report.id, field.id, FieldReview(action="confirm", reviewer="A"), NOW)
    assert field.verification_status == VerificationStatus.VERIFIED


def test_review_errors(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    other_tender = add_tender(session, "000002-2026")
    other_report = create_report(session, other_tender.id, VALID_REPORT)
    confirm = {"action": "confirm", "reviewer": "A"}

    with pytest.raises(ReportNotFoundError):
        review_field(session, 9999, report.fields[0].id, confirm)
    with pytest.raises(FieldNotFoundError) as excinfo:
        review_field(session, report.id, 9999, confirm)
    assert excinfo.value.code == "field_not_found"
    assert str(excinfo.value) == f"Il campo 9999 non appartiene al report {report.id}."
    # un campo di un altro report non è accessibile da questo
    with pytest.raises(FieldNotFoundError):
        review_field(session, report.id, other_report.fields[0].id, confirm)
    with pytest.raises(ReportValidationError):
        review_field(
            session, report.id, report.fields[0].id, {"action": "correct", "reviewer": "A"}
        )
    assert report.fields[0].verification_status == VerificationStatus.TO_VERIFY


def test_report_without_critical_fields_becomes_verified_at_first_review(
    session: Session, tender: Tender
) -> None:
    payload = report_payload(fields=[VALID_REPORT["fields"][2]])
    report = create_report(session, tender.id, payload)
    assert report.status == ReportStatus.TO_REVIEW
    review_field(
        session, report.id, report.fields[0].id, {"action": "confirm", "reviewer": "A"}, NOW
    )
    assert report.status == ReportStatus.VERIFIED


def test_reset_to_review_after_amendment_keeps_fields_and_last_label(
    session: Session, tender: Tender
) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    for f in report.fields:
        review_field(session, report.id, f.id, {"action": "confirm", "reviewer": "Anna"}, NOW)
    assert report.status == ReportStatus.VERIFIED
    label = report.ai_label

    assert reset_report_to_review(session, tender) is True
    assert report.status == ReportStatus.TO_REVIEW
    assert report.ai_label == label
    assert all(f.verification_status == VerificationStatus.VERIFIED for f in report.fields)
    # riverifica: una nuova conferma riporta il report a verified con nome e data aggiornati
    later = NOW + timedelta(days=3)
    review_field(
        session, report.id, report.fields[0].id, {"action": "confirm", "reviewer": "Bruno"}, later
    )
    assert report.status == ReportStatus.VERIFIED
    assert report.ai_label == "Contenuto generato con IA – revisionato da Bruno, 2026-10-18"


def test_review_without_now_uses_current_time(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    field = report.fields[0]
    review_field(session, report.id, field.id, {"action": "confirm", "reviewer": "A"})
    assert abs((datetime.now(UTC) - field.reviewed_at.replace(tzinfo=UTC)).total_seconds()) < 5
