"""Test di seed.py: popola il database ed è idempotente."""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.models import IngestionRun, Report, Tender
from backend.domain.repository import list_tenders
from backend.domain.seed import seed


def test_seed_creates_20_tenders_with_reports_and_runs(session: Session) -> None:
    assert seed(session, today=date(2026, 10, 15)) == 20
    assert session.scalar(select(func.count()).select_from(Tender)) == 20
    assert session.scalar(select(func.count()).select_from(Report)) == 2
    assert session.scalar(select(func.count()).select_from(IngestionRun)) == 2
    assert list_tenders(session, is_relevant=True).total > 0
    assert all(1 <= t.relevance_score <= 5 for t in session.scalars(select(Tender)))


def test_seed_is_idempotent(session: Session) -> None:
    seed(session, today=date(2026, 10, 15))
    assert seed(session, today=date(2026, 10, 15)) == 0
    assert session.scalar(select(func.count()).select_from(Tender)) == 20
    assert session.scalar(select(func.count()).select_from(Report)) == 2


def test_seed_report_labels_follow_contract(session: Session) -> None:
    seed(session, today=date(2026, 10, 15))
    labels = {r.status.value: r.ai_label for r in session.scalars(select(Report))}
    assert labels["to_review"] == "Contenuto generato con IA – da revisionare"
    assert labels["verified"].startswith("Contenuto generato con IA – revisionato da ")
    scores = [t.relevance_score for t in session.scalars(select(Tender))]
    assert None not in scores
