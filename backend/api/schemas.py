"""Schemi di risposta e di richiesta, identici a `docs/API_CONTRACT.yaml`."""

from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import Path, Query
from pydantic import AfterValidator, BaseModel, Field

ReportStatusFilter = Literal["none", "to_review", "verified"]
CpvCode = Annotated[str, Field(pattern=r"^[0-9]{8}$")]

# Limiti di sicurezza controllati nel codice, non nel contratto: gli AfterValidator non cambiano
# lo schema OpenAPI (la parità /docs-contratto resta), ma valori estremi danno 422 e non 500.
INT32_MAX = 2_147_483_647  # id e chiavi del database
MAX_PAGE = 1_000_000
MAX_AMOUNT = 10_000_000_000_000_000.0  # colonna Numeric(18, 2): 16 cifre intere
MIN_YEAR, MAX_YEAR = 1900, 2999


def at_most(maximum: float) -> AfterValidator:
    """Valore massimo controllato nel codice (non compare nello schema OpenAPI)."""

    def check(value: Any) -> Any:
        if value is not None and value > maximum:
            shown = int(maximum) if float(maximum).is_integer() else maximum
            raise ValueError(f"deve essere al massimo {shown}")
        return value

    return AfterValidator(check)


def _year_in_range(value: date | None) -> date | None:
    if value is not None and not MIN_YEAR <= value.year <= MAX_YEAR:
        raise ValueError(f"l'anno deve essere tra {MIN_YEAR} e {MAX_YEAR}")
    return value


def _without_nul(value: str | None) -> str | None:
    if value is not None and "\x00" in value:
        raise ValueError("contiene caratteri non validi (NUL)")
    return value


# Controlli aggiuntivi da affiancare a `Query(...)` o `Path(...)` nelle firme degli endpoint.
YEAR_RANGE = AfterValidator(_year_in_range)
NO_NUL = AfterValidator(_without_nul)

# Identificativo nel percorso: intero positivo e che entra nel database (0 e negativi sono 422).
PositiveId = Annotated[int, Path(ge=1), at_most(INT32_MAX)]
PageNumber = Annotated[int, Query(ge=1), at_most(MAX_PAGE)]


def contains_nul(value: Any) -> bool:
    """Vero se una stringa, o una stringa annidata in liste e dizionari, contiene NUL."""
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(contains_nul(k) or contains_nul(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return any(contains_nul(v) for v in value)
    return False


class Error(BaseModel):
    """Formato unico degli errori."""

    error: str
    message: str


class Tender(BaseModel):
    id: int
    publication_number: str
    title: str
    description: str | None
    buyer_name: str
    buyer_city: str | None
    cpv_codes: list[CpvCode]
    notice_type: str
    estimated_value: float | None
    currency: str | None = Field(min_length=3, max_length=3)
    publication_date: date
    submission_deadline: datetime | None
    ted_url: str
    documents_url: str | None
    relevance_score: int = Field(ge=1, le=5)
    is_relevant: bool
    discard_reason: str | None
    parent_publication_number: str | None
    report_status: ReportStatusFilter
    created_at: datetime
    updated_at: datetime


class TenderList(BaseModel):
    items: list[Tender]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class Document(BaseModel):
    id: int
    tender_id: int
    name: str
    url: str | None
    status: Literal["downloaded", "not_accessible", "pending"]
    local_path: str | None
    downloaded_at: datetime | None


class DocumentList(BaseModel):
    items: list[Document]


class ReportField(BaseModel):
    id: int
    report_id: int
    label: str
    value: str
    original_value: str | None
    source_doc: str
    source_page: int | None = Field(ge=1)
    is_critical: bool
    verification_status: Literal["to_verify", "verified"]
    reviewer: str | None
    reviewed_at: datetime | None


class Report(BaseModel):
    id: int
    tender_id: int
    summary: str
    status: Literal["to_review", "verified"]
    generated_at: datetime
    ai_label: str
    fields: list[ReportField]


class Deadline(BaseModel):
    tender_id: int
    publication_number: str
    title: str
    buyer_name: str
    submission_deadline: datetime
    relevance_score: int = Field(ge=1, le=5)
    days_left: int = Field(ge=0)
    urgency: Literal["high", "medium", "low"]


class DeadlineList(BaseModel):
    items: list[Deadline]


class Stats(BaseModel):
    new_tenders_today: int = Field(ge=0)
    relevant_tenders: int = Field(ge=0)
    deadlines_next_7_days: int = Field(ge=0)
    reports_to_verify: int = Field(ge=0)


class Run(BaseModel):
    id: int
    run_date: date
    started_at: datetime
    finished_at: datetime | None
    status: Literal["running", "success", "failed"]
    fetched_count: int = Field(ge=0)
    new_count: int = Field(ge=0)
    updated_count: int = Field(ge=0)
    relevant_count: int = Field(ge=0)
    error_message: str | None


class RunList(BaseModel):
    items: list[Run]


class RunAccepted(BaseModel):
    id: int
    status: Literal["running"]


class Health(BaseModel):
    status: Literal["ok"]
