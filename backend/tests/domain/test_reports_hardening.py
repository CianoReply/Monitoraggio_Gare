"""Test di robustezza dei report (T2.5): lunghezze, race sul 409, parità con lo schema, fuso orario,
messaggi delle date, ordine dei campi. Il confronto con lo schema non usa jsonschema."""

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain import reports as reports_module
from backend.domain.models import Report, ReportStatus, Tender, VerificationStatus
from backend.domain.reports import (
    MAX_LABEL_LENGTH,
    MAX_REVIEWER_LENGTH,
    MAX_SOURCE_DOC_LENGTH,
    FieldReview,
    ReportAlreadyExistsError,
    ReportCreate,
    ReportValidationError,
    create_report,
    get_report_for_tender,
    load_report_schema,
    review_field,
    validate_field_review,
    validate_report,
)
from backend.tests.domain.test_reports import (
    VALID_REPORT,
    add_tender,
    report_payload,
    with_field,
)

ROME = ZoneInfo("Europe/Rome")


@pytest.fixture
def tender(session: Session) -> Tender:
    return add_tender(session)


CONFIRM = {"action": "confirm", "reviewer": "Anna"}


# --- Lunghezze delle colonne ---


def test_too_long_label_and_source_doc_are_a_clear_422(session: Session, tender: Tender) -> None:
    payload = report_payload(
        fields=[
            {
                **VALID_REPORT["fields"][0],
                "label": "L" * (MAX_LABEL_LENGTH + 1),
                "source_doc": "D" * (MAX_SOURCE_DOC_LENGTH + 1),
            },
            {**VALID_REPORT["fields"][1], "label": "M" * 250},
        ]
    )
    with pytest.raises(ReportValidationError) as excinfo:
        create_report(session, tender.id, payload)
    assert excinfo.value.errors == [
        "fields.0.label: troppo lungo (201 caratteri, massimo 200)",
        "fields.0.source_doc: troppo lungo (501 caratteri, massimo 500)",
        "fields.1.label: troppo lungo (250 caratteri, massimo 200)",
    ]
    assert str(excinfo.value).startswith("Report non valido: fields.0.label: troppo lungo")
    assert session.query(Report).count() == 0


def test_values_at_the_column_limits_are_saved(session: Session, tender: Tender) -> None:
    field = {
        **VALID_REPORT["fields"][0],
        "label": "L" * MAX_LABEL_LENGTH,
        "source_doc": "D" * MAX_SOURCE_DOC_LENGTH,
        "value": "V" * 5000,
    }
    report = create_report(session, tender.id, report_payload(fields=[field]))
    assert len(report.fields[0].label) == MAX_LABEL_LENGTH
    assert len(report.fields[0].source_doc) == MAX_SOURCE_DOC_LENGTH


def test_too_long_reviewer_is_rejected_without_touching_the_field(
    session: Session, tender: Tender
) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    field = report.fields[0]
    review = {"action": "confirm", "reviewer": "R" * (MAX_REVIEWER_LENGTH + 1)}
    with pytest.raises(ReportValidationError, match="reviewer: troppo lungo") as excinfo:
        review_field(session, report.id, field.id, review)
    assert excinfo.value.code == "validation_error"
    assert field.verification_status == VerificationStatus.TO_VERIFY and field.reviewer is None


def test_reviewer_at_the_limit_fits_in_columns_and_label(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, report_payload(fields=[VALID_REPORT["fields"][2]]))
    name = "R" * MAX_REVIEWER_LENGTH
    review_field(session, report.id, report.fields[0].id, {"action": "confirm", "reviewer": name})
    assert report.status == ReportStatus.VERIFIED
    assert report.fields[0].reviewer == name
    assert name in report.ai_label and len(report.ai_label) <= 500


def test_correct_with_a_very_long_value_is_accepted(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, VALID_REPORT)  # value è un campo Text
    review = {"action": "correct", "value": "x" * 20_000, "reviewer": "Anna"}
    review_field(session, report.id, report.fields[0].id, review)
    assert len(report.fields[0].value) == 20_000


# --- Race sul 409 ---


def test_concurrent_creation_is_reported_as_409_and_session_stays_usable(
    session: Session, tender: Tender, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = create_report(session, tender.id, VALID_REPORT)
    real = reports_module._report_exists
    calls: list[int] = []

    def racing(sess: Session, tender_id: int) -> bool:
        calls.append(tender_id)
        return False if len(calls) == 1 else real(sess, tender_id)  # il controllo "perde" la gara

    monkeypatch.setattr(reports_module, "_report_exists", racing)
    with pytest.raises(ReportAlreadyExistsError) as excinfo:
        create_report(session, tender.id, VALID_REPORT)
    assert excinfo.value.code == "report_already_exists"
    assert isinstance(excinfo.value.__cause__, IntegrityError)
    # il savepoint ha annullato solo il tentativo: la sessione e il primo report sono intatti
    assert get_report_for_tender(session, tender.id) is first
    assert session.query(Report).count() == 1
    other = add_tender(session, "000002-2026")
    assert create_report(session, other.id, VALID_REPORT).id is not None


def test_integrity_error_not_caused_by_a_duplicate_is_not_hidden(
    session: Session, tender: Tender, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_report(session, tender.id, VALID_REPORT)
    monkeypatch.setattr(reports_module, "_report_exists", lambda sess, tender_id: False)
    with pytest.raises(IntegrityError):
        create_report(session, tender.id, VALID_REPORT)


# --- Parità dei vincoli tra report_schema.json e i modelli pydantic (senza jsonschema) ---


def _types(node: dict[str, Any]) -> frozenset[str]:
    declared = node.get("type")
    if declared is None:
        return frozenset()
    return frozenset([declared] if isinstance(declared, str) else declared)


def _constraints(node: dict[str, Any], defs: dict[str, Any], *, optional: bool = False) -> dict:
    """Vincoli confrontabili di un nodo di schema (JSON Schema scritto a mano o di pydantic).

    Per le proprietà facoltative la nullabilità non si confronta: pydantic le dichiara nullabili
    perché hanno un default None; il null esplicito è coperto dai casi dei test di validazione.
    """
    if "$ref" in node:
        return _constraints(defs[node["$ref"].rsplit("/", 1)[-1]], defs, optional=optional)
    if "anyOf" in node:  # tipo | null, come lo scrive pydantic
        branches = [b for b in node["anyOf"] if b.get("type") != "null"]
        nullable = len(branches) != len(node["anyOf"])
        result = _constraints(branches[0], defs, optional=optional)
        if nullable and not optional:
            result["types"] = result["types"] | {"null"}
        return result
    types = _types(node)
    if optional:
        types = types - {"null"}
    result: dict[str, Any] = {
        "types": types,
        "format": node.get("format"),
        "minLength": node.get("minLength"),
        "minimum": node.get("minimum"),
        "minItems": node.get("minItems"),
        "enum": tuple(node["enum"]) if "enum" in node else None,
    }
    if "properties" in node:
        required = frozenset(node.get("required", []))
        result["required"] = required
        result["additionalProperties"] = node.get("additionalProperties", True)
        result["properties"] = {
            name: _constraints(sub, defs, optional=name not in required)
            for name, sub in node["properties"].items()
        }
    if "items" in node:
        result["items"] = _constraints(node["items"], defs)
    return result


def _hand_written(name: str) -> dict:
    definitions = load_report_schema()["definitions"]
    return _constraints(definitions[name], definitions)


def _from_pydantic(model: type) -> dict:
    schema = model.model_json_schema()
    return _constraints(schema, schema.get("$defs", {}))


def test_report_create_constraints_match_between_schema_and_pydantic() -> None:
    assert _from_pydantic(ReportCreate) == _hand_written("ReportCreate")


def test_field_review_constraints_match_between_schema_and_pydantic() -> None:
    assert _from_pydantic(FieldReview) == _hand_written("FieldReview")


def test_field_review_conditional_requirement_is_in_the_schema() -> None:
    schema = load_report_schema()["definitions"]["FieldReview"]
    assert schema["if"] == {"properties": {"action": {"const": "correct"}}, "required": ["action"]}
    assert schema["then"] == {"required": ["value"]}
    with pytest.raises(ReportValidationError):  # e il modello lo applica
        validate_field_review({"action": "correct", "reviewer": "A"})


def test_constraint_comparison_detects_a_difference() -> None:
    mutated = _hand_written("ReportCreate")
    mutated["properties"]["fields"]["items"]["properties"]["label"]["minLength"] = 2
    assert _from_pydantic(ReportCreate) != mutated


# --- Data dell'etichetta in Europe/Rome e orari in UTC ---


def test_label_date_is_the_rome_date_not_the_utc_one(session: Session, tender: Tender) -> None:
    report = create_report(session, tender.id, report_payload(fields=[VALID_REPORT["fields"][2]]))
    just_after_midnight = datetime(2026, 10, 15, 0, 30, tzinfo=ROME)  # 22:30 UTC del giorno 14
    assert just_after_midnight.astimezone(UTC).date().isoformat() == "2026-10-14"
    review_field(session, report.id, report.fields[0].id, CONFIRM, now=just_after_midnight)
    assert report.ai_label == "Contenuto generato con IA – revisionato da Anna, 2026-10-15"


def test_label_date_before_rome_midnight_stays_on_the_same_day(
    session: Session, tender: Tender
) -> None:
    report = create_report(session, tender.id, report_payload(fields=[VALID_REPORT["fields"][2]]))
    late = datetime(2026, 10, 14, 23, 30, tzinfo=ROME)  # 21:30 UTC
    review_field(session, report.id, report.fields[0].id, CONFIRM, now=late)
    assert report.ai_label.endswith("Anna, 2026-10-14")
    winter = datetime(2026, 12, 15, 23, 30, tzinfo=UTC)  # 00:30 del 16 a Roma (ora solare)
    review_field(session, report.id, report.fields[0].id, CONFIRM, now=winter)
    assert report.ai_label.endswith("Anna, 2026-12-16")


def test_times_are_saved_in_utc(session: Session, tender: Tender) -> None:
    local = datetime(2026, 10, 15, 8, 0, tzinfo=ROME)
    payload = {k: v for k, v in VALID_REPORT.items() if k != "generated_at"}
    report = create_report(session, tender.id, payload, now=local)
    review_field(session, report.id, report.fields[0].id, CONFIRM, now=local)
    session.expire_all()  # SQLite non conserva il fuso: si rilegge dal database
    assert report.generated_at.replace(tzinfo=UTC) == datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
    assert report.fields[0].reviewed_at.replace(tzinfo=UTC) == datetime(
        2026, 10, 15, 6, 0, tzinfo=UTC
    )


def test_generated_at_with_offset_is_converted_to_utc(session: Session, tender: Tender) -> None:
    payload = report_payload(generated_at="2026-10-14T11:15:00+02:00")
    report = create_report(session, tender.id, payload)
    assert report.generated_at == datetime(2026, 10, 14, 9, 15, tzinfo=UTC)


def test_naive_now_is_rejected(session: Session, tender: Tender) -> None:
    naive = datetime(2026, 10, 15, 8, 0)
    with pytest.raises(ValueError, match="fuso orario"):
        create_report(session, tender.id, VALID_REPORT, now=naive)
    report = create_report(session, tender.id, VALID_REPORT)
    with pytest.raises(ValueError, match="fuso orario"):
        review_field(session, report.id, report.fields[0].id, CONFIRM, now=naive)
    assert report.fields[0].verification_status == VerificationStatus.TO_VERIFY


# --- Messaggi italiani per le date ---


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("2026-10-14T09:15:00", "generated_at: deve includere il fuso orario"),
        ("ieri", "generated_at: data non valida"),
        ("2026-13-45", "generated_at: data non valida"),
        ("2026-10-14T25:00:00+00:00", "generated_at: data non valida"),
        (1760000000, "generated_at: deve essere una stringa ISO 8601"),
        (None, "generated_at: non può essere null"),
        (["2026-10-14"], "generated_at: deve essere una stringa ISO 8601"),
    ],
)
def test_date_errors_are_in_italian(value: Any, message: str) -> None:
    with pytest.raises(ReportValidationError) as excinfo:
        validate_report(report_payload(generated_at=value))
    assert message in str(excinfo.value)
    assert "Input should" not in str(excinfo.value) and "Value error" not in str(excinfo.value)


def test_python_datetime_is_accepted_as_generated_at() -> None:
    parsed = validate_report(report_payload(generated_at=datetime(2026, 10, 14, 9, 15, tzinfo=UTC)))
    assert parsed.generated_at == datetime(2026, 10, 14, 9, 15, tzinfo=UTC)
    with pytest.raises(ReportValidationError, match="fuso orario"):
        validate_report(report_payload(generated_at=datetime(2026, 10, 14, 9, 15)))


def test_null_value_messages_are_italian() -> None:
    with pytest.raises(ReportValidationError, match="fields.0.value: deve essere una stringa"):
        validate_report(with_field(value=None))
    with pytest.raises(ReportValidationError, match="value: non può essere null"):
        validate_field_review({"action": "confirm", "value": None, "reviewer": "A"})


# --- Ordine dei campi ---


def test_fields_are_returned_in_insertion_order_after_reload(
    session: Session, tender: Tender
) -> None:
    report = create_report(session, tender.id, VALID_REPORT)
    labels = [f["label"] for f in VALID_REPORT["fields"]]
    session.expire_all()
    reloaded = get_report_for_tender(session, tender.id)
    assert [f.label for f in reloaded.fields] == labels
    ids = [f.id for f in reloaded.fields]
    assert ids == sorted(ids) and reloaded is report
