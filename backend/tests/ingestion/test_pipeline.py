"""Test del job giornaliero (T1.5): SQLite in memoria, avvisi dalle fixture reali, nessuna rete."""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import StaticPool, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend.domain import repository
from backend.domain.config import load_filters_config, load_scoring_config
from backend.domain.database import create_session_factory
from backend.domain.models import Base, IngestionRun, RunStatus, Tender
from backend.ingestion import pipeline
from backend.ingestion.dedup import ChainLookupError
from backend.ingestion.pipeline import (
    MAX_RECOVERY_DAYS,
    ROME,
    PipelineDeps,
    RunAlreadyRunningError,
    days_to_process,
    exclusive_run,
    run_daily_ingestion,
    run_pending_days,
    utc_now,
)
from backend.ingestion.scheduler import (
    JOB_ID,
    create_scheduler,
    daily_job,
    parse_schedule,
    start_scheduler,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 15, 6, 0, tzinfo=ROME)


def day_notices() -> list[dict[str, Any]]:
    data = json.loads((FIXTURES / "ted_search_it_2026-10-14.json").read_text(encoding="utf-8"))
    return data["response"]["notices"]


@pytest.fixture
def factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield create_session_factory(engine)
    engine.dispose()


class Recorder:
    """Finto `process_tender_documents`: registra le gare per cui è stato chiamato."""

    def __init__(self) -> None:
        self.tenders: list[str] = []

    def __call__(self, session: Session, tender: Tender, **kwargs: Any) -> list[Any]:
        self.tenders.append(tender.publication_number)
        return []


def make_deps(
    factory: sessionmaker[Session],
    fetch: Any = None,
    lookup: Any = None,
    recorder: Recorder | None = None,
    now: datetime = NOW,
) -> PipelineDeps:
    return PipelineDeps(
        session_factory=factory,
        fetch_notices=fetch or (lambda day: day_notices() if day == DAY else []),
        lookup=lookup or (lambda identifier: None),
        filters_config=load_filters_config(),
        scoring_config=load_scoring_config(),
        documents_config=None,
        process_documents=recorder or Recorder(),
        now=lambda: now,
    )


def runs(factory: sessionmaker[Session]) -> list[IngestionRun]:
    with factory() as session:
        return list(session.scalars(select(IngestionRun).order_by(IngestionRun.id)))


def tender_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.scalar(select(func.count()).select_from(Tender)) or 0


def test_utc_now_converts_to_utc() -> None:
    deps = PipelineDeps(now=lambda: NOW)
    assert utc_now(deps) == datetime(2026, 10, 15, 4, 0, tzinfo=UTC)


def test_days_to_process() -> None:
    today = date(2026, 10, 15)
    assert days_to_process(None, today) == [date(2026, 10, 14)]
    assert days_to_process(date(2026, 10, 14), today) == []
    assert days_to_process(date(2026, 10, 11), today) == [
        date(2026, 10, 12),
        date(2026, 10, 13),
        date(2026, 10, 14),
    ]


def test_days_to_process_is_limited_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        days = days_to_process(date(2026, 1, 1), date(2026, 10, 15))
    assert len(days) == MAX_RECOVERY_DAYS and days[-1] == date(2026, 10, 14)
    assert "Recupero limitato" in caplog.text


def test_run_daily_ingestion_saves_tenders_and_records_run(factory: sessionmaker[Session]) -> None:
    recorder = Recorder()
    summary = run_daily_ingestion(DAY, make_deps(factory, recorder=recorder))

    assert summary.status is RunStatus.SUCCESS
    assert summary.fetched_count == 9 and summary.new_count == 9 and summary.updated_count == 0
    assert tender_count(factory) == 9
    with factory() as session:
        relevant = session.scalars(select(Tender).where(Tender.is_relevant)).all()
        scores = session.scalars(select(Tender.relevance_score)).all()
    assert summary.relevant_count == len(relevant) > 0
    assert sorted(recorder.tenders) == sorted(t.publication_number for t in relevant)
    assert all(1 <= score <= 5 for score in scores)
    # gli esiti (can-standard) restano scartati dai filtri ma hanno un voto (ADR-010)
    with factory() as session:
        result = session.scalar(select(Tender).where(Tender.publication_number == "707979-2026"))
    assert result is not None and result.discard_reason and not result.is_relevant

    [run] = runs(factory)
    assert run.status is RunStatus.SUCCESS and run.run_date == DAY
    assert (run.fetched_count, run.new_count, run.relevant_count) == (9, 9, summary.relevant_count)
    assert run.finished_at is not None and run.error_message is None


def test_second_run_of_the_same_day_updates_without_duplicates(
    factory: sessionmaker[Session],
) -> None:
    run_daily_ingestion(DAY, make_deps(factory))
    summary = run_daily_ingestion(DAY, make_deps(factory))
    assert (summary.new_count, summary.updated_count) == (0, 9)
    assert tender_count(factory) == 9


def test_concurrent_run_is_rejected_when_one_is_running(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        repository.start_run(session, DAY, now=(NOW - timedelta(minutes=5)).astimezone(UTC))
        session.commit()
    with pytest.raises(RunAlreadyRunningError):
        run_daily_ingestion(DAY, make_deps(factory))
    assert tender_count(factory) == 0


def test_concurrent_run_is_rejected_by_process_lock(factory: sessionmaker[Session]) -> None:
    with exclusive_run():
        with pytest.raises(RunAlreadyRunningError):
            run_daily_ingestion(DAY, make_deps(factory))


def test_two_threads_only_one_runs(factory: sessionmaker[Session]) -> None:
    started = threading.Event()
    release = threading.Event()

    def slow_fetch(day: date) -> list[dict[str, Any]]:
        started.set()
        release.wait(5)
        return []

    errors: list[Exception] = []
    first = threading.Thread(target=run_daily_ingestion, args=(DAY, make_deps(factory, slow_fetch)))
    first.start()
    assert started.wait(5)
    try:
        run_daily_ingestion(DAY, make_deps(factory))
    except RunAlreadyRunningError as exc:
        errors.append(exc)
    release.set()
    first.join(5)
    assert not first.is_alive()
    assert len(errors) == 1
    assert [r.status for r in runs(factory)] == [RunStatus.SUCCESS]


def test_stale_running_run_is_closed_and_a_new_one_starts(factory: sessionmaker[Session]) -> None:
    with factory() as session:
        repository.start_run(session, DAY, now=(NOW - timedelta(hours=7)).astimezone(UTC))
        session.commit()
    summary = run_daily_ingestion(DAY, make_deps(factory))
    first, second = runs(factory)
    assert first.status is RunStatus.FAILED and "interrotta" in (first.error_message or "")
    assert second.status is RunStatus.SUCCESS and summary.run_id == second.id


def test_failure_is_recorded_with_readable_message(factory: sessionmaker[Session]) -> None:
    def broken_fetch(day: date) -> list[dict[str, Any]]:
        raise ConnectionError("TED non raggiungibile")

    summary = run_daily_ingestion(DAY, make_deps(factory, broken_fetch))
    assert summary.status is RunStatus.FAILED
    assert summary.error_message == "ConnectionError: TED non raggiungibile"
    [run] = runs(factory)
    assert run.status is RunStatus.FAILED and run.error_message == summary.error_message
    assert run.finished_at is not None


def test_notice_with_failed_chain_lookup_is_skipped(factory: sessionmaker[Session]) -> None:
    changes = json.loads(
        (FIXTURES / "ted_search_it_changes_2026-10.json").read_text(encoding="utf-8")
    )["response"]["notices"]

    def failing_lookup(identifier: str) -> dict[str, Any] | None:
        raise ChainLookupError("rete giù")

    deps = make_deps(factory, fetch=lambda day: [*day_notices(), changes[0]], lookup=failing_lookup)
    summary = run_daily_ingestion(DAY, deps)
    assert summary.status is RunStatus.SUCCESS
    assert summary.fetched_count == 10 and summary.new_count == 9 and summary.skipped_count == 1


def test_recovery_processes_failed_day_and_next_one(factory: sessionmaker[Session]) -> None:
    calls: list[date] = []

    def fetch(day: date) -> list[dict[str, Any]]:
        calls.append(day)
        if day == date(2026, 10, 13) and len(calls) == 1:
            raise TimeoutError("TED lento")
        return day_notices() if day == DAY else []

    # giorno 1: il 13 fallisce
    with factory() as session:
        repository.finish_run(
            session, repository.start_run(session, date(2026, 10, 12)), status=RunStatus.SUCCESS
        )
        session.commit()
    first = run_pending_days(make_deps(factory, fetch, now=datetime(2026, 10, 14, 6, tzinfo=ROME)))
    assert [(s.run_date, s.status) for s in first] == [(date(2026, 10, 13), RunStatus.FAILED)]

    # giorno dopo: si recuperano sia il 13 sia il 14
    second = run_pending_days(make_deps(factory, fetch, now=NOW))
    assert [(s.run_date, s.status) for s in second] == [
        (date(2026, 10, 13), RunStatus.SUCCESS),
        (date(2026, 10, 14), RunStatus.SUCCESS),
    ]
    assert tender_count(factory) == 9


def test_run_pending_days_first_start_processes_only_yesterday(
    factory: sessionmaker[Session],
) -> None:
    summaries = run_pending_days(make_deps(factory))
    assert [s.run_date for s in summaries] == [DAY]


def test_resolve_uses_given_dependencies(factory: sessionmaker[Session]) -> None:
    deps = make_deps(factory)
    resolved = pipeline._resolve(deps)
    assert resolved.session_factory is factory and resolved.fetch_notices is deps.fetch_notices
    assert resolved.documents_config is not None  # caricata da config.toml


@pytest.mark.parametrize(
    ("value", "expected"), [(None, (6, 0)), ("", (6, 0)), ("07:30", (7, 30)), (" 23:59 ", (23, 59))]
)
def test_parse_schedule(value: str | None, expected: tuple[int, int]) -> None:
    assert parse_schedule(value) == expected


@pytest.mark.parametrize("value", ["6", "24:00", "06:60", "ab:cd", "1:2:3"])
def test_parse_schedule_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        parse_schedule(value)


def test_scheduler_next_run_is_six_in_rome() -> None:
    scheduler = create_scheduler(6, 0, job=lambda: None)
    trigger = scheduler.get_job(JOB_ID).trigger
    next_fire = trigger.get_next_fire_time(None, datetime(2026, 10, 15, 7, 0, tzinfo=ROME))
    assert next_fire == datetime(2026, 10, 16, 6, 0, tzinfo=ROME)
    # ai cambi dell'ora legale resta alle 06:00 locali
    autumn = trigger.get_next_fire_time(None, datetime(2026, 10, 24, 7, 0, tzinfo=ROME))
    assert autumn == datetime(2026, 10, 25, 5, 0, tzinfo=UTC)
    spring = trigger.get_next_fire_time(None, datetime(2026, 3, 28, 7, 0, tzinfo=ROME))
    assert spring == datetime(2026, 3, 29, 4, 0, tzinfo=UTC)


def test_job_starts_at_the_configured_time() -> None:
    fired = threading.Event()
    target = datetime.now(ROME) + timedelta(seconds=2)
    scheduler = create_scheduler(target.hour, target.minute, job=fired.set, second=target.second)
    scheduler.start()
    try:
        assert fired.wait(10), "il job non è partito all'orario configurato"
    finally:
        scheduler.shutdown(wait=False)


def test_daily_job_ignores_already_running() -> None:
    def busy() -> None:
        raise RunAlreadyRunningError("in corso")

    daily_job(busy)  # non solleva


def test_daily_job_propagates_other_errors() -> None:
    def broken() -> None:
        raise RuntimeError("guasto")

    with pytest.raises(RuntimeError):
        daily_job(broken)


def test_start_scheduler_reads_schedule_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[bool] = []
    monkeypatch.setenv("INGESTION_SCHEDULE", "07:15")
    monkeypatch.setattr(
        "apscheduler.schedulers.background.BackgroundScheduler.start",
        lambda self, *args, **kwargs: started.append(True),
    )
    scheduler = start_scheduler()
    trigger = scheduler.get_job(JOB_ID).trigger
    next_fire = trigger.get_next_fire_time(None, datetime(2026, 10, 15, 8, 0, tzinfo=ROME))
    assert next_fire == datetime(2026, 10, 16, 7, 15, tzinfo=ROME)
    assert started == [True]


def test_run_for_today_or_future_is_rejected(factory: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError):
        run_daily_ingestion(date(2026, 10, 15), make_deps(factory))
    assert runs(factory) == []


def test_unexpected_error_on_one_notice_skips_only_that_notice(
    factory: sessionmaker[Session],
) -> None:
    poisoned = day_notices()[0]["publication-number"]

    class FailingRecorder(Recorder):
        def __call__(self, session: Session, tender: Tender, **kwargs: Any) -> list[Any]:
            if tender.publication_number == poisoned:
                raise RuntimeError("documenti illeggibili")
            return super().__call__(session, tender, **kwargs)

    summary = run_daily_ingestion(DAY, make_deps(factory, recorder=FailingRecorder()))
    assert summary.status is RunStatus.SUCCESS
    assert summary.skipped_count == 1
    with factory() as session:
        saved = session.scalars(select(Tender.publication_number)).all()
    assert poisoned not in saved and len(saved) == 8


def test_recovery_stops_when_another_run_is_in_progress(
    factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def busy(day: date, deps: PipelineDeps) -> Any:
        raise RunAlreadyRunningError("in corso")

    monkeypatch.setattr(pipeline, "run_daily_ingestion", busy)
    assert run_pending_days(make_deps(factory)) == []


def test_recovery_stops_at_first_failed_day(factory: sessionmaker[Session]) -> None:
    calls: list[date] = []

    def fetch(day: date) -> list[dict[str, Any]]:
        calls.append(day)
        raise TimeoutError("TED lento")

    with factory() as session:
        repository.finish_run(
            session, repository.start_run(session, date(2026, 10, 11)), status=RunStatus.SUCCESS
        )
        session.commit()
    summaries = run_pending_days(make_deps(factory, fetch))
    assert [s.run_date for s in summaries] == [date(2026, 10, 12)]
    assert calls == [date(2026, 10, 12)]


@pytest.fixture
def quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.ingestion.logging_config.configure_logging", lambda: None)


@pytest.mark.usefixtures("quiet_logging")
def test_main_runs_the_given_day(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[date] = []

    def fake_run(day: date, deps: PipelineDeps | None = None) -> Any:
        calls.append(day)
        return pipeline.RunSummary(run_id=1, run_date=day, status=RunStatus.SUCCESS)

    monkeypatch.setattr(pipeline, "run_daily_ingestion", fake_run)
    monkeypatch.setattr(pipeline, "run_pending_days", lambda: [])
    assert pipeline.main(["--date", "2026-10-14"]) == 0
    assert calls == [date(2026, 10, 14)]
    assert pipeline.main([]) == 0


@pytest.mark.usefixtures("quiet_logging")
def test_main_reports_failures_and_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    failed = pipeline.RunSummary(run_id=1, run_date=DAY, status=RunStatus.FAILED)
    monkeypatch.setattr(pipeline, "run_pending_days", lambda: [failed])
    assert pipeline.main([]) == 1

    def busy() -> list[Any]:
        raise RunAlreadyRunningError("in corso")

    monkeypatch.setattr(pipeline, "run_pending_days", busy)
    assert pipeline.main([]) == 2
