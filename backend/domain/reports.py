"""Archiviazione dei report della Skill e revisione dei campi (T2.5).

Il formato del report è descritto da `report_schema.json` (stesso schema di `ReportCreate` e
`FieldReview` di `docs/API_CONTRACT.yaml`). Qui la validazione è fatta con modelli pydantic,
senza la libreria jsonschema.

Regole:
- al massimo un report per gara (ADR-008);
- il report nasce `to_review`, con tutti i campi `to_verify` e `ai_label` "da revisionare";
- `confirm` e `correct` portano il campo a `verified`; `correct` conserva il valore della Skill in
  `original_value` (solo la prima correzione lo imposta);
- dopo ogni revisione lo stato del report è ricalcolato: `verified` solo se TUTTI i campi critici
  sono `verified` (un report senza campi critici diventa quindi `verified` alla prima revisione);
- quando il report è `verified`, `ai_label` riporta l'ultimo revisore e la data (AAAA-MM-GG);
  se torna `to_review` (es. dopo una rettifica) l'etichetta resta l'ultima fino alla riverifica.
  La data è quella di Europe/Rome; gli orari si salvano in UTC e `now` deve avere il fuso orario.

Le funzioni fanno solo `flush`. Gli errori sono eccezioni dedicate con `code` e `message`:
404 (`TenderNotFoundError`, `ReportNotFoundError`, `FieldNotFoundError`), 409
(`ReportAlreadyExistsError`), 422 (`ReportValidationError`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain.models import (
    FieldGroup,
    Report,
    ReportField,
    ReportStatus,
    Tender,
    VerificationStatus,
)
from backend.domain.timeutil import ROME, as_utc

REPORT_SCHEMA_PATH = Path(__file__).with_name("report_schema.json")
LABEL_TO_REVIEW = "Contenuto generato con IA – da revisionare"
# La data dell'etichetta è quella italiana (ROME), come in /deadlines.

# Lunghezze massime delle colonne (models.py). Il contratto non le dichiara (proposta per T4.3:
# aggiungere maxLength), quindi si controllano qui, dopo lo schema, per rispondere 422 e non 500.
MAX_LABEL_LENGTH = 200
MAX_SOURCE_DOC_LENGTH = 500
MAX_REVIEWER_LENGTH = 200


def label_verified(reviewer: str, day: date) -> str:
    """Etichetta di un report verificato: ultimo revisore e data AAAA-MM-GG."""
    return f"Contenuto generato con IA – revisionato da {reviewer}, {day.isoformat()}"


def load_report_schema() -> dict[str, Any]:
    """Legge `report_schema.json` (formato che produce la Skill)."""
    return json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))


# --- Eccezioni (l'API le mappa a 404, 409 e 422) ---


class ReportError(Exception):
    """Errore del dominio dei report: `code` è il codice dell'API, `message` il testo."""

    code = "report_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TenderNotFoundError(ReportError):
    """404: la gara non esiste."""

    code = "tender_not_found"

    def __init__(self, tender_id: int) -> None:
        super().__init__(f"La gara {tender_id} non esiste.")


class ReportNotFoundError(ReportError):
    """404: il report (o la gara senza report) non esiste."""

    code = "report_not_found"


class FieldNotFoundError(ReportError):
    """404: il campo non esiste o non appartiene al report."""

    code = "field_not_found"

    def __init__(self, report_id: int, field_id: int) -> None:
        super().__init__(f"Il campo {field_id} non appartiene al report {report_id}.")


class ReportAlreadyExistsError(ReportError):
    """409: la gara ha già un report (ADR-008)."""

    code = "report_already_exists"

    def __init__(self, tender_id: int) -> None:
        super().__init__(f"La gara {tender_id} ha già un report.")


class ReportValidationError(ReportError, ValueError):
    """422: il report o la revisione non rispettano lo schema. `errors` elenca i problemi."""

    code = "validation_error"

    def __init__(self, what: str, errors: list[str]) -> None:
        super().__init__(f"{what} non valido: " + "; ".join(errors))
        self.errors = errors


# --- Modelli di validazione (equivalenti a report_schema.json) ---


class ReportFieldCreate(BaseModel):
    """Un campo del report prodotto dalla Skill."""

    model_config = ConfigDict(extra="forbid")

    label: StrictStr = Field(min_length=1)
    value: StrictStr = Field(min_length=1)
    source_doc: StrictStr = Field(min_length=1)
    source_page: StrictInt | None = Field(default=None, ge=1)
    is_critical: StrictBool


class ReportCreate(BaseModel):
    """Report prodotto dalla Skill (corpo di `POST /tenders/{id}/report`)."""

    model_config = ConfigDict(extra="forbid")

    summary: StrictStr = Field(min_length=1)
    generated_at: AwareDatetime | None = None
    fields: list[ReportFieldCreate] = Field(min_length=1)

    @field_validator("generated_at", mode="before")
    @classmethod
    def _only_iso_string(cls, value: Any) -> Any:
        """Come nello schema (`type: string`): niente null esplicito né numeri."""
        if value is None:
            raise ValueError("non può essere null")
        if not isinstance(value, str | datetime):
            raise ValueError("deve essere una stringa ISO 8601")
        return value


class FieldReview(BaseModel):
    """Revisione di un campo (corpo di `PATCH /reports/{id}/fields/{field_id}`)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm", "correct"]
    value: StrictStr | None = Field(default=None, min_length=1)
    reviewer: StrictStr = Field(min_length=1)

    @field_validator("value", mode="before")
    @classmethod
    def _value_not_null(cls, value: Any) -> Any:
        """Come nello schema (`type: string`): se c'è, `value` non può essere null."""
        if value is None:
            raise ValueError("non può essere null")
        return value

    @model_validator(mode="after")
    def _correct_needs_value(self) -> Self:
        if self.action == "correct" and self.value is None:
            raise ValueError("value è obbligatorio con action=correct")
        return self


_MESSAGES = {
    "missing": "campo obbligatorio",
    "extra_forbidden": "campo non previsto",
    "string_too_short": "non può essere vuoto",
    "too_short": "deve contenere almeno un elemento",
    "greater_than_equal": "deve essere un intero >= 1",
    "string_type": "deve essere una stringa",
    "int_type": "deve essere un intero",
    "bool_type": "deve essere vero o falso",
    "list_type": "deve essere una lista",
    "dict_type": "deve essere un oggetto",
    "literal_error": "valore non ammesso (usa confirm o correct)",
    "model_type": "deve essere un oggetto",
    "timezone_aware": "deve includere il fuso orario (es. +01:00)",
    "datetime_type": "deve essere una data e ora in formato ISO 8601",
    "datetime_parsing": "data e ora non valide (usa ISO 8601, es. 2026-10-14T09:15:00+00:00)",
    "datetime_from_date_parsing": "data non valida (usa ISO 8601, es. 2026-10-14T09:15:00+00:00)",
}


def _describe(error: Mapping[str, Any]) -> str:
    where = ".".join(str(part) for part in error["loc"]) or "(documento)"
    message = _MESSAGES.get(error["type"])
    if message is None:
        message = str(error["msg"]).removeprefix("Value error, ")
    return f"{where}: {message}"


def _validate[T: BaseModel](model: type[T], payload: Any, what: str) -> T:
    if isinstance(payload, model):
        return payload
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ReportValidationError(what, [_describe(e) for e in exc.errors()]) from exc


def validate_report(payload: Mapping[str, Any] | ReportCreate) -> ReportCreate:
    """Valida un report contro lo schema; solleva `ReportValidationError` con i problemi."""
    return _validate(ReportCreate, payload, "Report")


def validate_field_review(payload: Mapping[str, Any] | FieldReview) -> FieldReview:
    """Valida una revisione di campo; solleva `ReportValidationError`."""
    return _validate(FieldReview, payload, "Revisione")


NUL = chr(0)
MAX_SOURCE_PAGE = 2_147_483_647  # intero a 32 bit della colonna `source_page`


def _text_errors(where: str, value: str, maximum: int | None = None) -> list[str]:
    """Problemi che il database non accetta: testo troppo lungo per la colonna o con NUL."""
    errors = []
    if maximum is not None and len(value) > maximum:
        errors.append(f"{where}: troppo lungo ({len(value)} caratteri, massimo {maximum})")
    if NUL in value:
        errors.append(f"{where}: non può contenere il carattere NUL")
    return errors


def _check_report_limits(data: ReportCreate) -> None:
    """Limiti delle colonne non dichiarati dal contratto: 422 chiaro, mai un errore del database."""
    errors = _text_errors("summary", data.summary)
    for i, field in enumerate(data.fields):
        prefix = f"fields.{i}"
        errors += _text_errors(f"{prefix}.label", field.label, MAX_LABEL_LENGTH)
        errors += _text_errors(f"{prefix}.value", field.value)
        errors += _text_errors(f"{prefix}.source_doc", field.source_doc, MAX_SOURCE_DOC_LENGTH)
        if field.source_page is not None and field.source_page > MAX_SOURCE_PAGE:
            errors.append(f"{prefix}.source_page: troppo grande (massimo {MAX_SOURCE_PAGE})")
    if errors:
        raise ReportValidationError("Report", errors)


def _check_review_limits(data: FieldReview) -> None:
    errors = _text_errors("reviewer", data.reviewer, MAX_REVIEWER_LENGTH)
    if data.value is not None:
        errors += _text_errors("value", data.value)
    if errors:
        raise ReportValidationError("Revisione", errors)


def _report_exists(session: Session, tender_id: int) -> bool:
    return session.scalar(select(Report.id).where(Report.tender_id == tender_id)) is not None


# --- Funzioni per l'API ---


def get_report(session: Session, report_id: int) -> Report:
    """Report per id; `ReportNotFoundError` se non esiste."""
    report = session.get(Report, report_id)
    if report is None:
        raise ReportNotFoundError(f"Il report {report_id} non esiste.")
    return report


def get_report_for_tender(session: Session, tender_id: int) -> Report:
    """Report della gara. `TenderNotFoundError` se la gara non esiste, `ReportNotFoundError`
    se non ha ancora un report."""
    if session.get(Tender, tender_id) is None:
        raise TenderNotFoundError(tender_id)
    report = session.scalar(select(Report).where(Report.tender_id == tender_id))
    if report is None:
        raise ReportNotFoundError(f"La gara {tender_id} non ha ancora un report.")
    return report


def create_report(
    session: Session,
    tender_id: int,
    payload: Mapping[str, Any] | ReportCreate,
    now: datetime | None = None,
) -> Report:
    """Salva il report della Skill per la gara.

    Errori: `ReportValidationError` (422), `TenderNotFoundError` (404),
    `ReportAlreadyExistsError` (409). Il report nasce `to_review` con tutti i campi `to_verify`
    e l'etichetta "da revisionare"; `generated_at` è quello della Skill o l'istante di `now`.
    """
    data = validate_report(payload)
    _check_report_limits(data)
    created_at = as_utc(now)
    if session.get(Tender, tender_id) is None:
        raise TenderNotFoundError(tender_id)
    if _report_exists(session, tender_id):
        raise ReportAlreadyExistsError(tender_id)
    report = Report(
        tender_id=tender_id,
        summary=data.summary,
        status=ReportStatus.TO_REVIEW,
        generated_at=data.generated_at.astimezone(UTC) if data.generated_at else created_at,
        ai_label=LABEL_TO_REVIEW,
        fields=[
            ReportField(
                label=f.label,
                value=f.value,
                source_doc=f.source_doc,
                source_page=f.source_page,
                is_critical=f.is_critical,
                group=FieldGroup.REQUIREMENTS if f.is_critical else FieldGroup.KEY_INFO,
                verification_status=VerificationStatus.TO_VERIFY,
            )
            for f in data.fields
        ],
    )
    try:
        # savepoint: se una richiesta concorrente ha creato il report, la sessione resta usabile
        with session.begin_nested():
            session.add(report)
            session.flush()
    except IntegrityError as exc:
        if _report_exists(session, tender_id):
            raise ReportAlreadyExistsError(tender_id) from exc
        raise
    return report


def compute_report_status(report: Report) -> ReportStatus:
    """`verified` solo se tutti i campi critici sono `verified`, altrimenti `to_review`."""
    all_confirmed = all(
        f.verification_status == VerificationStatus.VERIFIED for f in report.fields if f.is_critical
    )
    return ReportStatus.VERIFIED if all_confirmed else ReportStatus.TO_REVIEW


def review_field(
    session: Session,
    report_id: int,
    field_id: int,
    review: Mapping[str, Any] | FieldReview,
    now: datetime | None = None,
) -> Report:
    """Conferma o corregge un campo e ricalcola lo stato del report; restituisce il report.

    `confirm`: il campo diventa `verified`. `correct`: `value` sostituisce il valore, il valore
    precedente va in `original_value` (solo alla prima correzione) e il campo diventa `verified`.
    In entrambi i casi si salvano `reviewer` e `reviewed_at`. Se il report risulta `verified`,
    `ai_label` indica l'ultimo revisore e la data.
    Errori: `ReportValidationError` (422), `ReportNotFoundError` / `FieldNotFoundError` (404).
    """
    data = validate_field_review(review)
    _check_review_limits(data)
    moment = as_utc(now)
    report = get_report(session, report_id)
    field = next((f for f in report.fields if f.id == field_id), None)
    if field is None:
        raise FieldNotFoundError(report_id, field_id)

    if data.action == "correct":
        if field.original_value is None:
            field.original_value = field.value
        field.value = data.value or field.value
    field.verification_status = VerificationStatus.VERIFIED
    field.reviewer = data.reviewer
    field.reviewed_at = moment

    report.status = compute_report_status(report)
    if report.status == ReportStatus.VERIFIED:
        report.ai_label = label_verified(data.reviewer, moment.astimezone(ROME).date())
    session.flush()
    return report
