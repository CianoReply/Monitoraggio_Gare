"""Test di osservazione, decisioni e liste del frontend (ADR-016), su SQLite in memoria."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.domain import repository, workflow
from backend.domain.models import DecisionStatus, Tender, WatchStatus
from backend.domain.schemas import TenderEvaluation
from backend.domain.timeutil import ROME
from backend.tests.domain.conftest import make_tender

NOW = datetime(2026, 10, 16, 9, 0, tzinfo=ROME)
TODAY = date(2026, 10, 16)


def add(session: Session, number: str, *, discarded: bool = False, **overrides: object) -> Tender:
    data = make_tender(publication_number=number, **overrides)
    evaluation = TenderEvaluation(
        relevance_score=int(overrides.pop("score", 3)) if "score" in overrides else 3,
        is_relevant=not discarded,
        discard_reason="scartata" if discarded else None,
    )
    return repository.upsert_tender(session, data, evaluation).tender


def deadline(days: int) -> datetime:
    return NOW + timedelta(days=days)


def test_set_watch_sets_watched_at_when_becoming_active(session: Session) -> None:
    tender = add(session, "1-2026", submission_deadline=deadline(5))
    workflow.set_watch(session, tender, WatchStatus.WATCHING, NOW)
    assert tender.watch_status is WatchStatus.WATCHING
    assert tender.watched_at == NOW.astimezone(UTC)

    later = NOW + timedelta(days=1)
    workflow.set_watch(session, tender, WatchStatus.CANDIDATE, later)
    assert tender.watched_at == NOW.astimezone(UTC)  # già attiva: data invariata

    workflow.set_watch(session, tender, WatchStatus.NONE, later)
    assert tender.watch_status is WatchStatus.NONE
    assert tender.watched_at == NOW.astimezone(UTC)  # non si azzera


def test_set_watch_restarts_when_deadline_has_passed(session: Session) -> None:
    tender = add(session, "1-2026", submission_deadline=deadline(-3))
    tender.watch_status = WatchStatus.WATCHING
    tender.watched_at = (NOW - timedelta(days=10)).astimezone(UTC)
    workflow.set_watch(session, tender, WatchStatus.TO_DEEPEN, NOW)
    assert tender.watched_at == NOW.astimezone(UTC)


def test_is_active_watch(session: Session) -> None:
    tender = add(session, "1-2026", submission_deadline=deadline(0))
    assert not workflow.is_active_watch(tender, TODAY)
    tender.watch_status = WatchStatus.DISCARDED
    assert workflow.is_active_watch(tender, TODAY)  # scade oggi: ancora attiva
    tender.submission_deadline = None
    assert workflow.is_active_watch(tender, TODAY)
    tender.submission_deadline = deadline(-1)
    assert not workflow.is_active_watch(tender, TODAY)


def test_set_decision_records_who_and_when(session: Session) -> None:
    tender = add(session, "1-2026")
    workflow.set_decision(
        session, tender, DecisionStatus.DEEPENED, "Da approfondire", " F. Ciano ", NOW
    )
    assert tender.decision_status is DecisionStatus.DEEPENED
    assert tender.decision_reason == "Da approfondire"
    assert tender.decided_by == "F. Ciano"
    assert tender.decided_at == NOW.astimezone(UTC)
    workflow.set_decision(session, tender, DecisionStatus.DISCARDED, "", "B", NOW)
    assert tender.decision_status is DecisionStatus.DISCARDED


@pytest.mark.parametrize(
    ("reason", "user"),
    [("a\x00b", "x"), ("x" * 2001, "x"), ("ok", ""), ("ok", "u" * 201), ("ok", "a\x00")],
)
def test_set_decision_rejects_invalid_text(session: Session, reason: str, user: str) -> None:
    tender = add(session, "1-2026")
    with pytest.raises(ValueError):
        workflow.set_decision(session, tender, DecisionStatus.MONITORED, reason, user, NOW)


def test_set_watch_and_decision_require_timezone(session: Session) -> None:
    tender = add(session, "1-2026")
    with pytest.raises(ValueError):
        workflow.set_watch(session, tender, WatchStatus.WATCHING, datetime(2026, 10, 16))


def test_list_published_on_excludes_discarded_and_orders_by_score(session: Session) -> None:
    add(session, "1-2026", publication_date=TODAY, score=2)
    add(session, "2-2026", publication_date=TODAY, score=5)
    add(session, "3-2026", publication_date=TODAY, discarded=True)
    add(session, "4-2026", publication_date=TODAY - timedelta(days=1))
    numbers = [t.publication_number for t in workflow.list_published_on(session, TODAY)]
    assert numbers == ["2-2026", "1-2026"]


def test_list_active_watch(session: Session) -> None:
    soon = add(session, "1-2026", submission_deadline=deadline(2))
    later = add(session, "2-2026", submission_deadline=deadline(9))
    expired = add(session, "3-2026", submission_deadline=deadline(-2))
    open_ended = add(session, "4-2026", submission_deadline=None)
    add(session, "5-2026", submission_deadline=deadline(1))  # non osservata
    for t in (later, soon, expired, open_ended):
        t.watch_status = WatchStatus.WATCHING
    session.flush()
    numbers = [t.publication_number for t in workflow.list_active_watch(session, TODAY)]
    assert numbers == ["1-2026", "2-2026", "4-2026"]


def test_list_decided_newest_first(session: Session) -> None:
    first = add(session, "1-2026")
    second = add(session, "2-2026")
    add(session, "3-2026")
    workflow.set_decision(session, first, DecisionStatus.MONITORED, "", "A", NOW)
    workflow.set_decision(
        session, second, DecisionStatus.CANDIDATE, "", "A", NOW + timedelta(hours=1)
    )
    assert [t.publication_number for t in workflow.list_decided(session)] == ["2-2026", "1-2026"]


def test_search(session: Session) -> None:
    add(session, "1-2026", title="Piattaforma cloud regionale")
    add(session, "2-2026", title="Cloud per i comuni", discarded=True)
    add(session, "3-2026", title="Pulizia uffici")
    found = {t.publication_number for t in workflow.search(session, "cloud")}
    assert found == {"1-2026", "2-2026"}
    assert workflow.search(session, "   ") == []
