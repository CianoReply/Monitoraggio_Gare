"""Schemi di risposta e di richiesta, identici a `docs/API_CONTRACT.yaml`."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReportStatusFilter = Literal["none", "to_review", "verified"]


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
    cpv_codes: list[str]
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


class ReportFieldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    value: str = Field(min_length=1)
    source_doc: str = Field(min_length=1)
    source_page: int | None = Field(default=None, ge=1)
    is_critical: bool


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    generated_at: datetime | None = None
    fields: list[ReportFieldCreate] = Field(min_length=1)


class FieldReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["confirm", "correct"]
    value: str | None = Field(default=None, min_length=1)
    reviewer: str = Field(min_length=1)

    @model_validator(mode="after")
    def value_required_for_correct(self) -> "FieldReview":
        if self.action == "correct" and self.value is None:
            raise ValueError("value è obbligatorio con action=correct")
        return self


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
