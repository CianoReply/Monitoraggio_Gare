"""Test di timeutil e del tipo UtcDateTime: fusi coerenti su SQLite e PostgreSQL."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from backend.domain.database import create_session_factory
from backend.domain.models import IngestionRun, RunStatus, Tender, UtcDateTime
from backend.domain.repository import start_run, upsert_tender
from backend.domain.schemas import TenderEvaluation
from backend.domain.timeutil import ROME, as_utc, utcnow
from backend.tests.domain.conftest import make_tender


def test_rome_is_the_single_europe_rome_zone() -> None:
    from backend.domain import reports, repository

    assert ROME.key == "Europe/Rome"
    assert repository.ROME is ROME and reports.ROME is ROME


def test_utcnow_is_aware_utc() -> None:
    now = utcnow()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)


def test_as_utc_converts_none_and_rejects_naive() -> None:
    local = datetime(2026, 10, 15, 8, 0, tzinfo=ROME)
    assert as_utc(local) == datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
    assert as_utc(local).tzinfo is UTC
    assert abs((as_utc(None) - datetime.now(UTC)).total_seconds()) < 5
    with pytest.raises(ValueError, match="fuso orario"):
        as_utc(datetime(2026, 10, 15, 8, 0))


def test_utc_datetime_round_trip_from_a_new_session(engine: Engine) -> None:
    factory = create_session_factory(engine)
    deadline = datetime(2026, 11, 20, 12, 0, tzinfo=timezone(timedelta(hours=1)))
    with factory() as writer:
        tender, _ = upsert_tender(
            writer, make_tender(submission_deadline=deadline), TenderEvaluation(3, True)
        )
        run = start_run(writer, date(2026, 10, 14), now=datetime(2026, 10, 15, 8, 0, tzinfo=ROME))
        writer.commit()
        tender_id, run_id = tender.id, run.id

    with factory() as reader:  # sessione nuova: i valori arrivano dal database
        tender = reader.get(Tender, tender_id)
        run = reader.get(IngestionRun, run_id)
        assert tender is not None and run is not None
        assert tender.submission_deadline == deadline
        assert tender.submission_deadline.tzinfo is not None
        assert tender.submission_deadline.utcoffset() == timedelta(0)
        assert run.started_at == datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
        assert run.finished_at is None and run.status == RunStatus.RUNNING
        assert tender.created_at.tzinfo is not None and tender.updated_at.tzinfo is not None


def test_comparing_aware_values_read_from_database(engine: Engine) -> None:
    factory = create_session_factory(engine)
    with factory() as session:
        upsert_tender(
            session,
            make_tender(submission_deadline=datetime(2026, 11, 20, 12, 0, tzinfo=UTC)),
            TenderEvaluation(3, True),
        )
        session.commit()
    with factory() as session:
        deadline = session.scalars(select(Tender.submission_deadline)).one()
        assert deadline - datetime(2026, 11, 1, tzinfo=UTC) == timedelta(days=19, hours=12)


def test_naive_values_written_to_the_database_are_treated_as_utc(session: Session) -> None:
    tender, _ = upsert_tender(session, make_tender(), TenderEvaluation(3, True))
    tender.created_at = datetime(2026, 10, 15, 6, 0)  # senza fuso
    session.commit()
    session.expire_all()
    assert tender.created_at == datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


def test_none_is_kept_as_none(session: Session) -> None:
    tender, _ = upsert_tender(
        session, make_tender(submission_deadline=None), TenderEvaluation(3, True)
    )
    session.commit()
    session.expire_all()
    assert tender.submission_deadline is None


def test_utc_datetime_type_converts_both_ways() -> None:
    column_type = UtcDateTime()
    rome = datetime(2026, 7, 1, 14, 0, tzinfo=ROME)
    assert column_type.process_bind_param(rome, None) == datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    assert column_type.process_bind_param(None, None) is None
    assert column_type.process_result_value(datetime(2026, 7, 1, 12, 0), None) == datetime(
        2026, 7, 1, 12, 0, tzinfo=UTC
    )
    assert column_type.process_result_value(rome, None) == rome
    assert column_type.process_result_value(None, None) is None
