"""Seed coerente con le regole del dominio e campione che non si ferma su dati non validi."""

import io
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.config import load_filters_config, load_scoring_config
from backend.domain.filters import filter_notice_type
from backend.domain.models import Report, ReportStatus, Tender, VerificationStatus
from backend.domain.scoring_sample import _to_create, print_sample
from backend.domain.seed import seed
from backend.domain.timeutil import ROME

TODAY = date(2026, 10, 15)
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_seed_notice_types_pass_the_notice_type_filter(session: Session) -> None:
    seed(session, today=TODAY)
    config = load_filters_config()
    tenders = list(session.scalars(select(Tender)))
    assert {t.notice_type for t in tenders} == {"cn-standard"}
    assert all(filter_notice_type(_to_create(t), config).kept for t in tenders)


def test_seed_verified_report_has_reviewer_and_review_time(session: Session) -> None:
    seed(session, today=TODAY)
    reports = {r.status: r for r in session.scalars(select(Report))}
    verified = reports[ReportStatus.VERIFIED]
    critical = [f for f in verified.fields if f.is_critical]
    assert critical and all(f.verification_status == VerificationStatus.VERIFIED for f in critical)
    assert all(f.reviewer == "Mario Rossi" for f in critical)
    assert all(f.reviewed_at is not None and f.reviewed_at.tzinfo is not None for f in critical)
    assert verified.ai_label == "Contenuto generato con IA – revisionato da Mario Rossi, 2026-10-15"
    to_review = reports[ReportStatus.TO_REVIEW]
    assert all(f.reviewer is None and f.reviewed_at is None for f in to_review.fields)
    assert to_review.ai_label == "Contenuto generato con IA – da revisionare"


def test_seed_report_deadline_value_uses_the_rome_date(session: Session) -> None:
    seed(session, today=TODAY)
    for report in session.scalars(select(Report)):
        tender = report.tender
        assert tender.submission_deadline is not None
        expected = str(tender.submission_deadline.astimezone(ROME).date())
        assert report.fields[0].value == expected


def test_seed_default_day_is_today_in_rome(session: Session) -> None:
    before = datetime.now(ROME).date()
    seed(session)
    after = datetime.now(ROME).date()
    newest = max(t.publication_date for t in session.scalars(select(Tender)))
    assert before - timedelta(days=0) <= newest <= after


def test_sample_survives_stored_data_that_no_longer_validates(session: Session) -> None:
    seed(session, today=TODAY)
    broken = session.scalars(select(Tender).order_by(Tender.id)).first()
    assert broken is not None
    broken.cpv_codes = ["non-un-cpv"]
    session.flush()
    stream = io.StringIO()
    count = print_sample(session, load_scoring_config(), limit=20, now=NOW, out=stream)
    text = stream.getvalue()
    assert count == 20
    assert "dati non validi, punteggio non ricalcolabile" in text
    assert "cpv_codes" in text
    assert text.count("criteri:") == 19  # tutte le altre gare sono stampate normalmente
