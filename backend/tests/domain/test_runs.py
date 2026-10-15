"""Test del registro delle esecuzioni (start_run, finish_run, ...)."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from backend.domain.models import RunStatus
from backend.domain.repository import (
    finish_run,
    get_run,
    get_running_run,
    has_successful_run,
    last_successful_run_date,
    list_runs,
    start_run,
)

T0 = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


def test_start_run_creates_running_run(session: Session) -> None:
    run = start_run(session, date(2026, 10, 14), now=T0)
    assert run.id is not None
    assert (run.run_date, run.status, run.started_at) == (date(2026, 10, 14), RunStatus.RUNNING, T0)
    assert run.finished_at is None
    assert (run.fetched_count, run.new_count, run.updated_count, run.relevant_count) == (0, 0, 0, 0)


def test_start_run_defaults_started_at_to_now(session: Session) -> None:
    run = start_run(session, date(2026, 10, 14))
    assert run.started_at is not None
    assert abs((datetime.now(UTC) - run.started_at.replace(tzinfo=UTC)).total_seconds()) < 5


def test_finish_run_success_saves_counts_and_finish_time(session: Session) -> None:
    run = start_run(session, date(2026, 10, 14), now=T0)
    done = finish_run(
        session,
        run,
        status=RunStatus.SUCCESS,
        fetched_count=120,
        new_count=18,
        updated_count=2,
        relevant_count=11,
        now=T0 + timedelta(minutes=4),
    )
    assert done is run
    assert run.status == RunStatus.SUCCESS
    assert run.finished_at == T0 + timedelta(minutes=4)
    assert (run.fetched_count, run.new_count, run.updated_count, run.relevant_count) == (
        120,
        18,
        2,
        11,
    )
    assert run.error_message is None


def test_finish_run_failed_keeps_error_message(session: Session) -> None:
    run = start_run(session, date(2026, 10, 14), now=T0)
    finish_run(session, run, status=RunStatus.FAILED, error_message="TED non raggiungibile")
    assert run.status == RunStatus.FAILED
    assert run.error_message == "TED non raggiungibile"
    assert run.finished_at is not None
    assert run.fetched_count == 0


@pytest.mark.parametrize("status", [RunStatus.RUNNING])
def test_finish_run_rejects_non_final_status(session: Session, status: RunStatus) -> None:
    run = start_run(session, date(2026, 10, 14))
    with pytest.raises(ValueError, match="success o failed"):
        finish_run(session, run, status=status)
    assert run.status == RunStatus.RUNNING


def test_finish_run_rejects_negative_counts(session: Session) -> None:
    run = start_run(session, date(2026, 10, 14))
    with pytest.raises(ValueError, match=">= 0"):
        finish_run(session, run, status=RunStatus.SUCCESS, new_count=-1)


def test_get_running_run_returns_most_recent_running(session: Session) -> None:
    assert get_running_run(session) is None
    old = start_run(session, date(2026, 10, 12), now=T0)
    done = start_run(session, date(2026, 10, 13), now=T0 + timedelta(hours=1))
    finish_run(session, done, status=RunStatus.SUCCESS)
    assert get_running_run(session) is old
    newer = start_run(session, date(2026, 10, 14), now=T0 + timedelta(hours=2))
    assert get_running_run(session) is newer
    finish_run(session, newer, status=RunStatus.FAILED)
    finish_run(session, old, status=RunStatus.FAILED)
    assert get_running_run(session) is None


def test_has_successful_run_only_counts_success(session: Session) -> None:
    day = date(2026, 10, 14)
    assert has_successful_run(session, day) is False
    run = start_run(session, day)
    assert has_successful_run(session, day) is False  # running
    finish_run(session, run, status=RunStatus.FAILED)
    assert has_successful_run(session, day) is False
    retry = start_run(session, day)
    finish_run(session, retry, status=RunStatus.SUCCESS)
    assert has_successful_run(session, day) is True
    assert has_successful_run(session, date(2026, 10, 13)) is False


def test_last_successful_run_date_is_the_maximum_run_date(session: Session) -> None:
    assert last_successful_run_date(session) is None
    for day, status in [
        (date(2026, 10, 10), RunStatus.SUCCESS),
        (date(2026, 10, 12), RunStatus.SUCCESS),
        (date(2026, 10, 11), RunStatus.SUCCESS),
        (date(2026, 10, 13), RunStatus.FAILED),
    ]:
        finish_run(session, start_run(session, day), status=status)
    start_run(session, date(2026, 10, 14))  # running: non conta
    assert last_successful_run_date(session) == date(2026, 10, 12)


def test_list_runs_most_recent_first_with_limit(session: Session) -> None:
    runs = [
        start_run(session, date(2026, 10, 10 + i), now=T0 + timedelta(hours=i)) for i in range(5)
    ]
    listed = list_runs(session)
    assert listed == list(reversed(runs))
    assert list_runs(session, limit=2) == [runs[4], runs[3]]
    assert list_runs(session, limit=100) == list(reversed(runs))


def test_list_runs_breaks_ties_by_id(session: Session) -> None:
    first = start_run(session, date(2026, 10, 14), now=T0)
    second = start_run(session, date(2026, 10, 14), now=T0)
    assert list_runs(session) == [second, first]


def test_list_runs_empty_and_invalid_limit(session: Session) -> None:
    assert list_runs(session) == []
    with pytest.raises(ValueError, match="limit"):
        list_runs(session, limit=0)


ROME = ZoneInfo("Europe/Rome")


def test_run_times_are_stored_in_utc(session: Session) -> None:
    local = datetime(2026, 10, 15, 8, 0, tzinfo=ROME)  # 06:00 UTC (ora legale)
    run = start_run(session, date(2026, 10, 14), now=local)
    finish_run(
        session, run, status=RunStatus.SUCCESS, now=datetime(2026, 10, 15, 8, 30, tzinfo=ROME)
    )
    session.expire(run)  # rilegge dal database: SQLite non conserva il fuso
    assert run.started_at.replace(tzinfo=UTC) == datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
    assert run.finished_at is not None
    assert run.finished_at.replace(tzinfo=UTC) == datetime(2026, 10, 15, 6, 30, tzinfo=UTC)
    assert (run.finished_at - run.started_at) == timedelta(minutes=30)


def test_naive_times_are_rejected(session: Session) -> None:
    with pytest.raises(ValueError, match="fuso orario"):
        start_run(session, date(2026, 10, 14), now=datetime(2026, 10, 15, 8, 0))
    run = start_run(session, date(2026, 10, 14), now=T0)
    with pytest.raises(ValueError, match="fuso orario"):
        finish_run(session, run, status=RunStatus.SUCCESS, now=datetime(2026, 10, 15, 8, 0))
    assert run.status == RunStatus.RUNNING and run.finished_at is None


def test_get_run_returns_the_run_or_none(session: Session) -> None:
    run = start_run(session, date(2026, 10, 14), now=T0)
    assert get_run(session, run.id) is run
    assert get_run(session, run.id + 1000) is None
