"""API per il frontend Monitoraggio_Gare_FE, sotto `/api` (ADR-016).

Implementa il contratto del §6 di `Monitoraggio_Gare_FE/HANDOFF.md` (tipi in `src/api/types.ts`),
traducendo dal dominio. Non fa parte di `docs/API_CONTRACT.yaml` e non compare in `/docs`.
- "Gare di oggi" = gare non scartate del giorno elaborato dall'ultima esecuzione riuscita del job
  (il job delle 06:00 elabora le pubblicazioni TED del giorno prima); senza esecuzioni: ieri.
- Date con ora nel formato del frontend: ora locale di Roma senza fuso, `AAAA-MM-GGTHH:MM`.
- Chi decide o rivede un campo: intestazione `X-User-Name`, altrimenti `FRONTEND_DEFAULT_USER`.
  Non è un'identità verificata (ADR-015).
"""

import os
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.api.deps import get_now, get_session
from backend.api.errors import ApiError
from backend.domain import repository, workflow
from backend.domain.models import (
    DecisionStatus,
    DocumentStatus,
    ReportField,
    RunStatus,
    Tender,
    VerificationStatus,
    WatchStatus,
)
from backend.domain.reports import review_field
from backend.domain.timeutil import ROME
from backend.ingestion.scheduler import parse_schedule

router = APIRouter(prefix="/api", include_in_schema=False)

DEFAULT_USER = "Utente frontend"
MAX_ID = 2_147_483_647

SessionDep = Annotated[Session, Depends(get_session)]
NowDep = Annotated[datetime, Depends(get_now)]


# --- Schemi (src/api/types.ts del frontend) ---------------------------------------------


class FeDecision(BaseModel):
    status: str
    reason: str
    decided_at: str
    decided_by: str


class FeDocument(BaseModel):
    name: str
    status: Literal["downloaded", "unavailable"]
    url: str


class FeReportField(BaseModel):
    id: str
    group: str
    label: str
    value: str
    source_doc: str
    source_page: int | None
    verification_status: Literal["to_review", "verified"]
    reviewer: str | None
    reviewed_at: str | None
    corrected: bool


class FeReport(BaseModel):
    summary: str
    fields: list[FeReportField]


class FeTender(BaseModel):
    id: str
    publication_number: str
    title: str
    buyer_name: str
    cpv_codes: list[str]
    estimated_value: float | None
    publication_date: str
    submission_deadline: str | None
    relevance_score: int
    report_status: Literal["absent", "to_review", "verified"]
    watch_status: str
    watched_at: str | None
    decision: FeDecision | None
    documents: list[FeDocument]
    report: FeReport | None


class MonitoringStatus(BaseModel):
    state: Literal["ok", "running", "failed"]
    last_run_at: str | None
    next_run_at: str


class WatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    watch_status: WatchStatus


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: DecisionStatus
    reason: str = Field(default="", max_length=workflow.MAX_REASON)


class ReportFieldUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verification_status: Literal["verified"]
    value: str | None = Field(default=None, min_length=1)


# --- Conversioni ------------------------------------------------------------------------


def local_minutes(moment: datetime | None) -> str | None:
    """Ora locale di Roma nel formato del frontend: `AAAA-MM-GGTHH:MM`."""
    return moment.astimezone(ROME).strftime("%Y-%m-%dT%H:%M") if moment else None


def local_day(moment: datetime | None) -> str | None:
    """Giorno di Roma in formato ISO (`AAAA-MM-GG`)."""
    return moment.astimezone(ROME).date().isoformat() if moment else None


def to_fe_field(field: ReportField) -> FeReportField:
    return FeReportField(
        id=str(field.id),
        group=field.group.value,
        label=field.label,
        value=field.value,
        source_doc=field.source_doc,
        source_page=field.source_page,
        verification_status=(
            "verified" if field.verification_status is VerificationStatus.VERIFIED else "to_review"
        ),
        reviewer=field.reviewer,
        reviewed_at=local_day(field.reviewed_at),
        corrected=field.original_value is not None,
    )


def to_fe_documents(tender: Tender) -> list[FeDocument]:
    """Documenti della gara; senza righe in `documents` si mostra il link indicato nell'avviso."""
    docs = [
        FeDocument(
            name=d.name,
            status="downloaded" if d.status is DocumentStatus.DOWNLOADED else "unavailable",
            url=d.url or tender.documents_url or tender.ted_url,
        )
        for d in tender.documents
    ]
    if not docs and tender.documents_url:
        docs.append(
            FeDocument(name="Documenti di gara", status="unavailable", url=tender.documents_url)
        )
    return docs


def to_fe_tender(tender: Tender) -> FeTender:
    """Gara completa nel formato del frontend."""
    report = tender.report
    decision = None
    if tender.decision_status is not None and tender.decided_at is not None:
        decision = FeDecision(
            status=tender.decision_status.value,
            reason=tender.decision_reason or "",
            decided_at=local_day(tender.decided_at) or "",
            decided_by=tender.decided_by or "",
        )
    return FeTender(
        id=str(tender.id),
        publication_number=tender.publication_number,
        title=tender.title,
        buyer_name=tender.buyer_name,
        cpv_codes=list(tender.cpv_codes or []),
        estimated_value=float(tender.estimated_value)
        if tender.estimated_value is not None
        else None,
        publication_date=tender.publication_date.isoformat(),
        submission_deadline=local_minutes(tender.submission_deadline),
        relevance_score=tender.relevance_score,
        report_status="absent" if report is None else report.status.value,
        watch_status=tender.watch_status.value,
        watched_at=local_day(tender.watched_at),
        decision=decision,
        documents=to_fe_documents(tender),
        report=(
            FeReport(summary=report.summary, fields=[to_fe_field(f) for f in report.fields])
            if report is not None
            else None
        ),
    )


def to_fe_list(tenders: Sequence[Tender]) -> list[FeTender]:
    return [to_fe_tender(t) for t in tenders]


def next_run_at(now: datetime) -> datetime:
    """Prossimo avvio del job secondo `INGESTION_SCHEDULE` (ora di Roma)."""
    hour, minute = parse_schedule(os.environ.get("INGESTION_SCHEDULE"))
    local = now.astimezone(ROME)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > local else candidate + timedelta(days=1)


def current_user(x_user_name: str | None) -> str:
    """Nome dell'utente dall'intestazione `X-User-Name`, altrimenti quello predefinito."""
    name = (x_user_name or "").strip() or os.environ.get("FRONTEND_DEFAULT_USER", "").strip()
    return (name or DEFAULT_USER)[:200]


def load_tender(session: Session, tender_id: str) -> Tender:
    if not tender_id.isdigit() or int(tender_id) > MAX_ID:
        raise ApiError(404, "tender_not_found", f"Gara {tender_id[:40]} non trovata.")
    tender = repository.get_tender(session, int(tender_id))
    if tender is None:
        raise ApiError(404, "tender_not_found", f"Gara {tender_id} non trovata.")
    return tender


def digest_day(session: Session, now: datetime) -> date:
    """Giorno TED mostrato come "oggi": l'ultimo elaborato con successo, altrimenti ieri."""
    return repository.last_successful_run_date(session) or (
        now.astimezone(ROME).date() - timedelta(days=1)
    )


# --- Endpoint ---------------------------------------------------------------------------


@router.get("/monitoring/status")
def get_monitoring_status(session: SessionDep, now: NowDep) -> MonitoringStatus:
    runs = repository.list_runs(session, limit=1)
    last = runs[0] if runs else None
    state: Literal["ok", "running", "failed"] = "ok"
    if last is not None and last.status is RunStatus.RUNNING:
        state = "running"
    elif last is not None and last.status is RunStatus.FAILED:
        state = "failed"
    last_at = (last.finished_at or last.started_at) if last is not None else None
    return MonitoringStatus(
        state=state,
        last_run_at=local_minutes(last_at),
        next_run_at=local_minutes(next_run_at(now)) or "",
    )


@router.get("/tenders")
def list_frontend_tenders(
    session: SessionDep,
    now: NowDep,
    published: Annotated[Literal["today"] | None, Query()] = None,
    watch: Annotated[Literal["active"] | None, Query()] = None,
    decided: Annotated[Literal["true"] | None, Query()] = None,
) -> list[FeTender]:
    if sum(v is not None for v in (published, watch, decided)) != 1:
        raise ApiError(
            422,
            "validation_error",
            "Indicare uno solo tra published=today, watch=active e decided=true.",
        )
    if published is not None:
        return to_fe_list(workflow.list_published_on(session, digest_day(session, now)))
    if watch is not None:
        return to_fe_list(workflow.list_active_watch(session, now.astimezone(ROME).date()))
    return to_fe_list(workflow.list_decided(session))


@router.get("/tenders/{tender_id}")
def get_frontend_tender(tender_id: str, session: SessionDep) -> FeTender:
    return to_fe_tender(load_tender(session, tender_id))


@router.get("/search")
def search_tenders(
    session: SessionDep, q: Annotated[str, Query(max_length=200)] = ""
) -> list[FeTender]:
    if "\x00" in q:
        raise ApiError(422, "validation_error", "q: contiene un carattere non valido.")
    return to_fe_list(workflow.search(session, q))


@router.put("/tenders/{tender_id}/watch")
def put_watch(tender_id: str, body: WatchUpdate, session: SessionDep, now: NowDep) -> FeTender:
    tender = load_tender(session, tender_id)
    workflow.set_watch(session, tender, body.watch_status, now)
    session.commit()
    return to_fe_tender(tender)


@router.post("/tenders/{tender_id}/decision")
def post_decision(
    tender_id: str,
    body: DecisionInput,
    session: SessionDep,
    now: NowDep,
    x_user_name: Annotated[str | None, Header()] = None,
) -> FeTender:
    tender = load_tender(session, tender_id)
    try:
        workflow.set_decision(
            session, tender, body.status, body.reason, current_user(x_user_name), now
        )
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    session.commit()
    return to_fe_tender(tender)


@router.patch("/tenders/{tender_id}/report/fields/{field_id}")
def patch_report_field(
    tender_id: str,
    field_id: str,
    body: ReportFieldUpdate,
    session: SessionDep,
    now: NowDep,
    x_user_name: Annotated[str | None, Header()] = None,
) -> FeTender:
    tender = load_tender(session, tender_id)
    if tender.report is None:
        raise ApiError(404, "report_not_found", f"La gara {tender_id} non ha un report.")
    if not field_id.isdigit() or int(field_id) > MAX_ID:
        raise ApiError(404, "field_not_found", f"Campo {field_id[:40]} non trovato.")
    review = {
        "action": "correct" if body.value is not None else "confirm",
        "reviewer": current_user(x_user_name),
    }
    if body.value is not None:
        review["value"] = body.value
    review_field(session, tender.report.id, int(field_id), review, now)
    session.commit()
    session.refresh(tender)
    return to_fe_tender(tender)
