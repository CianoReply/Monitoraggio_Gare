"""Test di GET /stats (T3.5): le attese si contano a mano sul database. Senza rete.

Oggi (orologio fisso) è il 15/10/2026, 14:00 a Roma.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS31Validator, oas31_format_checker
from sqlalchemy import Engine, StaticPool, create_engine, select
from sqlalchemy.orm import Session

from backend.domain.database import create_session_factory
from backend.domain.models import Base, Report, ReportStatus, Tender
from backend.tests.api_db import FIXED_NOW, make_app, make_seeded_engine
from backend.tests.contract_utils import resolve

ROME = ZoneInfo("Europe/Rome")
TODAY = FIXED_NOW.astimezone(ROME).date()


@pytest.fixture
def engine() -> Engine:
    return make_seeded_engine()


@pytest.fixture
def db(engine: Engine) -> Session:
    with create_session_factory(engine)() as session:
        yield session  # type: ignore[misc]


def _stats(engine: Engine, **kwargs: datetime) -> dict:
    response = TestClient(make_app(engine, **kwargs)).get("/stats")
    assert response.status_code == 200, response.text
    return response.json()


def _manual_counts(db: Session) -> dict[str, int]:
    """Conteggio a mano dei quattro indicatori, indipendente dal repository."""
    tenders = db.scalars(select(Tender)).all()
    week_end = TODAY + timedelta(days=7)

    def created_today(t: Tender) -> bool:
        created = t.created_at if t.created_at.tzinfo else t.created_at.replace(tzinfo=UTC)
        return created.astimezone(ROME).date() == TODAY

    def due_this_week(t: Tender) -> bool:
        if t.submission_deadline is None or not t.is_relevant:
            return False
        deadline = t.submission_deadline
        deadline = deadline if deadline.tzinfo else deadline.replace(tzinfo=UTC)
        return TODAY <= deadline.astimezone(ROME).date() <= week_end

    return {
        "new_tenders_today": sum(created_today(t) for t in tenders),
        "relevant_tenders": sum(t.is_relevant for t in tenders),
        "deadlines_next_7_days": sum(due_this_week(t) for t in tenders),
        "reports_to_verify": len(
            db.scalars(select(Report).where(Report.status == ReportStatus.TO_REVIEW)).all()
        ),
    }


def _set_created(db: Session, created: list[datetime]) -> None:
    for tender, moment in zip(
        db.scalars(select(Tender).order_by(Tender.id)), created, strict=False
    ):
        tender.created_at = moment
    db.commit()


@pytest.mark.contract
def test_stats_conform_to_contract(engine: Engine, spec: dict) -> None:
    body = _stats(engine)
    media = spec["paths"]["/stats"]["get"]["responses"]["200"]
    schema = resolve(spec, media)["content"]["application/json"]["schema"]
    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
    assert [e.message for e in validator.iter_errors(body)] == []
    assert set(body) == {
        "new_tenders_today",
        "relevant_tenders",
        "deadlines_next_7_days",
        "reports_to_verify",
    }


def test_stats_match_manual_count_on_seed_data(engine: Engine, db: Session) -> None:
    # Le gare del seed hanno created_at reale: le porto a giorni noti.
    ids = db.scalars(select(Tender.id).order_by(Tender.id)).all()
    midday_today = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
    created = [
        midday_today if i % 3 == 0 else midday_today - timedelta(days=2) for i in range(len(ids))
    ]
    _set_created(db, created)
    # Tre gare rilevanti con scadenza oggi, tra 3 e tra 7 giorni (le altre sono più lontane).
    relevant = db.scalars(select(Tender).where(Tender.is_relevant.is_(True)).order_by(Tender.id))
    for tender, days in zip(relevant, (0, 3, 7), strict=False):
        tender.submission_deadline = datetime(2026, 10, 15, 12, 0, tzinfo=UTC) + timedelta(
            days=days
        )
    db.commit()
    expected = _manual_counts(db)
    assert _stats(engine) == expected
    # Gli indicatori non sono banali: il confronto non vale per caso.
    assert all(value > 0 for value in expected.values())


def test_reports_to_verify_counts_reports_of_discarded_tenders_too(
    engine: Engine, db: Session
) -> None:
    discarded = db.scalars(
        select(Tender).where(Tender.discard_reason.is_not(None), Tender.report == None)  # noqa: E711
    ).first()
    assert discarded is not None
    before = _stats(engine)["reports_to_verify"]
    db.add(
        Report(
            tender_id=discarded.id,
            summary="x",
            status=ReportStatus.TO_REVIEW,
            ai_label="Contenuto generato con IA – da revisionare",
        )
    )
    db.commit()
    assert _stats(engine)["reports_to_verify"] == before + 1


@pytest.mark.parametrize(
    ("created", "counted"),
    [
        (datetime(2026, 10, 14, 22, 0, tzinfo=UTC), True),  # 00:00 del 15/10 a Roma
        (datetime(2026, 10, 14, 21, 59, 59, tzinfo=UTC), False),  # 23:59:59 del 14/10
        (datetime(2026, 10, 15, 21, 59, 59, tzinfo=UTC), True),  # 23:59:59 del 15/10
        (datetime(2026, 10, 15, 22, 0, tzinfo=UTC), False),  # 00:00 del 16/10
        (datetime(2026, 10, 15, 12, 0, tzinfo=UTC), True),
    ],
)
def test_new_tenders_today_uses_rome_day_boundaries(
    db: Session, created: datetime, counted: bool
) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    from backend.domain.repository import upsert_tender
    from backend.domain.schemas import TenderEvaluation
    from backend.tests.domain.conftest import make_tender

    with create_session_factory(engine)() as session:
        tender, _ = upsert_tender(session, make_tender(), TenderEvaluation(3, True))
        tender.created_at = created
        session.commit()
    assert _stats(engine)["new_tenders_today"] == (1 if counted else 0)


def test_deadlines_next_7_days_window_is_today_to_today_plus_7(db: Session) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    from backend.domain.repository import upsert_tender
    from backend.domain.schemas import TenderEvaluation
    from backend.tests.domain.conftest import make_tender

    offsets = [-1, 0, 7, 8]
    with create_session_factory(engine)() as session:
        for index, offset in enumerate(offsets):
            deadline = datetime(2026, 10, 15, 12, 0, tzinfo=UTC) + timedelta(days=offset)
            upsert_tender(
                session,
                make_tender(publication_number=f"{index:06d}-2026", submission_deadline=deadline),
                TenderEvaluation(3, True),
            )
        upsert_tender(  # non rilevante: non conta
            session,
            make_tender(
                publication_number="999999-2026",
                submission_deadline=datetime(2026, 10, 16, 12, 0, tzinfo=UTC),
            ),
            TenderEvaluation(2, False),
        )
        session.commit()
    assert _stats(engine)["deadlines_next_7_days"] == 2  # oggi e oggi + 7


def test_stats_on_empty_database_are_all_zero() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    assert _stats(engine) == {
        "new_tenders_today": 0,
        "relevant_tenders": 0,
        "deadlines_next_7_days": 0,
        "reports_to_verify": 0,
    }


def test_today_follows_the_clock_in_rome(engine: Engine, db: Session) -> None:
    ids = db.scalars(select(Tender.id).order_by(Tender.id)).all()
    # Tutte create alle 23:30 UTC del 15/10 = 01:30 del 16/10 a Roma.
    _set_created(db, [datetime(2026, 10, 15, 23, 30, tzinfo=UTC)] * len(ids))
    assert _stats(engine)["new_tenders_today"] == 0
    assert _stats(engine, now=datetime(2026, 10, 15, 23, 45, tzinfo=UTC))[
        "new_tenders_today"
    ] == len(ids)
