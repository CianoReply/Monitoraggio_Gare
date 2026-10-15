"""Test di deduplica e rettifiche (T1.4): SQLite in memoria e fixture reali TED, senza rete.

Catena reale delle fixture: 437009-2026 (originale) ← 566426-2026 ← 687833-2026 (rettifiche).
"""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import StaticPool, create_engine, func, select
from sqlalchemy.orm import Session

from backend.domain.database import create_session_factory
from backend.domain.models import Base, Report, ReportStatus, Tender
from backend.domain.schemas import TenderEvaluation
from backend.ingestion.dedup import (
    MAX_CHAIN_DEPTH,
    ChainLink,
    ChainLookupError,
    TedNoticeLookup,
    notice_order_key,
    resolve_chain,
    save_notice,
)
from backend.ingestion.parser import parse_notice

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EVALUATION = TenderEvaluation(relevance_score=3, is_relevant=True)
ORIGINAL = "437009-2026"
FIRST_CHANGE = "566426-2026"
SECOND_CHANGE = "687833-2026"


def load_notices(name: str) -> dict[str, dict[str, Any]]:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return {n["publication-number"]: n for n in data["response"]["notices"]}


RAW = {
    **load_notices("ted_lookup_change_predecessors.json"),
    **load_notices("ted_search_it_changes_2026-10.json"),
    **load_notices("ted_search_it_2026-10-14.json"),
}
BY_IDENTIFIER = {n["notice-identifier"]: n for n in RAW.values()}


def lookup(notice_identifier: str) -> dict[str, Any] | None:
    return BY_IDENTIFIER.get(notice_identifier)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as s:
        yield s
    engine.dispose()


def save(session: Session, publication_number: str) -> Any:
    return save_notice(session, parse_notice(RAW[publication_number]), EVALUATION, lookup)


def count_tenders(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Tender)) or 0


def add_report(session: Session, tender: Tender, status: ReportStatus) -> Report:
    report = Report(tender_id=tender.id, summary="Sintesi", status=status, ai_label="etichetta")
    session.add(report)
    session.flush()
    return report


def test_resolve_chain_walks_to_the_original() -> None:
    chain = resolve_chain(RAW[SECOND_CHANGE], lookup)
    assert [link.publication_number for link in chain.links] == [FIRST_CHANGE, ORIGINAL]
    assert chain.links[0] == ChainLink(FIRST_CHANGE, "68d34303-2d11-45ec-ae35-19a735ee975d")
    assert chain.complete


def test_resolve_chain_of_a_non_change_notice_is_empty() -> None:
    chain = resolve_chain(RAW[ORIGINAL], lookup)
    assert chain.links == [] and chain.complete


def test_resolve_chain_stops_when_ted_does_not_find_the_notice(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        chain = resolve_chain(RAW[SECOND_CHANGE], lambda _: None)
    assert chain.links == [] and not chain.complete
    assert "non trovato" in caplog.text


def test_resolve_chain_stops_on_cycles() -> None:
    looping = {"publication-number": "1-2026", "change-notice-version-identifier": "abc-01"}
    chain = resolve_chain(looping, lambda _: looping)
    assert [link.publication_number for link in chain.links] == ["1-2026"]
    assert not chain.complete


def test_resolve_chain_has_a_maximum_depth() -> None:
    counter = iter(range(1000))

    def endless(_: str) -> dict[str, Any]:
        n = next(counter)
        return {"publication-number": f"{n}-2026", "change-notice-version-identifier": f"id{n}-01"}

    start = {"change-notice-version-identifier": "start-01"}
    chain = resolve_chain(start, endless)
    assert len(chain.links) == MAX_CHAIN_DEPTH and not chain.complete


def test_ted_notice_lookup_caches_results() -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def search(query: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
        calls.append((query, fields))
        return [RAW[ORIGINAL]] if "216bf55d" in query else []

    ted_lookup = TedNoticeLookup(search)
    assert ted_lookup("216bf55d-4a9c-4db2-8f57-5c487a33feda") == RAW[ORIGINAL]
    assert ted_lookup("216bf55d-4a9c-4db2-8f57-5c487a33feda") == RAW[ORIGINAL]
    assert ted_lookup("sconosciuto") is None
    assert len(calls) == 2
    assert calls[0][0] == "notice-identifier=216bf55d-4a9c-4db2-8f57-5c487a33feda"


def test_importing_the_same_day_twice_creates_no_duplicates(session: Session) -> None:
    day = load_notices("ted_search_it_2026-10-14.json")
    for _ in range(2):
        for number in day:
            save(session, number)
    assert count_tenders(session) == len(day)


def test_second_import_reports_update_not_creation(session: Session) -> None:
    assert save(session, "707611-2026").created is True
    outcome = save(session, "707611-2026")
    assert outcome.created is False
    assert outcome.is_change is False


def test_change_updates_deadline_of_the_original(session: Session) -> None:
    save(session, ORIGINAL)
    outcome = save(session, FIRST_CHANGE)
    tender = outcome.tender
    assert outcome.is_change and not outcome.created
    assert outcome.original_publication_number == ORIGINAL
    assert tender.publication_number == ORIGINAL
    assert count_tenders(session) == 1
    # scadenza della rettifica: 2026-10-14 13:00+02:00 (originale: 2026-09-14)
    deadline = tender.submission_deadline
    assert deadline is not None
    assert deadline.replace(tzinfo=UTC) == datetime(2026, 10, 14, 11, 0, tzinfo=UTC)
    assert tender.raw_data["publication-number"] == FIRST_CHANGE


def test_second_change_in_the_chain_reaches_the_original(session: Session) -> None:
    save(session, ORIGINAL)
    outcome = save(session, SECOND_CHANGE)
    assert outcome.tender.publication_number == ORIGINAL
    assert count_tenders(session) == 1


def test_change_resets_existing_report_to_review(session: Session) -> None:
    original = save(session, ORIGINAL).tender
    report = add_report(session, original, ReportStatus.VERIFIED)
    outcome = save(session, FIRST_CHANGE)
    assert outcome.report_reset is True
    session.refresh(report)
    assert report.status == ReportStatus.TO_REVIEW


def test_change_without_report_resets_nothing(session: Session) -> None:
    save(session, ORIGINAL)
    assert save(session, FIRST_CHANGE).report_reset is False


def test_change_without_original_is_saved_on_its_own(
    session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        outcome = save(session, FIRST_CHANGE)
    assert outcome.created is True
    assert outcome.tender.publication_number == FIRST_CHANGE
    assert outcome.tender.parent_publication_number == ORIGINAL
    assert "senza gara originale" in caplog.text


def test_later_change_updates_a_change_saved_on_its_own(session: Session) -> None:
    save(session, FIRST_CHANGE)
    outcome = save(session, SECOND_CHANGE)
    assert outcome.tender.publication_number == FIRST_CHANGE
    assert count_tenders(session) == 1


def test_reimporting_the_original_does_not_undo_a_change(session: Session) -> None:
    save(session, ORIGINAL)
    save(session, FIRST_CHANGE)
    outcome = save(session, ORIGINAL)
    assert outcome.created is False
    assert outcome.skipped_as_older is True
    assert outcome.tender.raw_data["publication-number"] == FIRST_CHANGE


def test_resolve_chain_wraps_lookup_errors() -> None:
    def failing(_: str) -> dict[str, Any] | None:
        raise TimeoutError("TED non risponde")

    with pytest.raises(ChainLookupError, match="TED non risponde"):
        resolve_chain(RAW[FIRST_CHANGE], failing)


def test_resolve_chain_stops_on_predecessor_without_number() -> None:
    chain = resolve_chain(RAW[FIRST_CHANGE], lambda _: {"notice-identifier": "x"})
    assert chain.links == [] and not chain.complete


def test_notice_order_key_orders_by_date_then_number() -> None:
    assert notice_order_key(RAW[ORIGINAL]) < notice_order_key(RAW[FIRST_CHANGE])
    assert notice_order_key(RAW[FIRST_CHANGE]) < notice_order_key(RAW[SECOND_CHANGE])
    same_day = {"publication-date": "2026-10-14+02:00"}
    assert notice_order_key({**same_day, "publication-number": "9-2026"}) < notice_order_key(
        {**same_day, "publication-number": "10-2026"}
    )
    assert notice_order_key({}) == ("", 0, 0)


def deadline_of(tender: Tender) -> datetime | None:
    deadline = tender.submission_deadline
    return deadline.replace(tzinfo=UTC) if deadline and deadline.tzinfo is None else deadline


def test_changes_in_reverse_order_keep_the_newest(session: Session) -> None:
    save(session, ORIGINAL)
    newest = save(session, SECOND_CHANGE).tender
    newest_deadline = deadline_of(newest)
    outcome = save(session, FIRST_CHANGE)
    assert outcome.skipped_as_older is True
    assert outcome.tender.raw_data["publication-number"] == SECOND_CHANGE
    assert deadline_of(outcome.tender) == newest_deadline
    assert count_tenders(session) == 1


def test_same_change_imported_twice_is_idempotent(session: Session) -> None:
    save(session, ORIGINAL)
    first = save(session, FIRST_CHANGE)
    second = save(session, FIRST_CHANGE)
    assert second.skipped_as_older is False
    assert deadline_of(second.tender) == deadline_of(first.tender)
    assert count_tenders(session) == 1


def test_lookup_error_writes_nothing(session: Session) -> None:
    def failing(_: str) -> dict[str, Any] | None:
        raise ConnectionError("rete giù")

    with pytest.raises(ChainLookupError):
        save_notice(session, parse_notice(RAW[FIRST_CHANGE]), EVALUATION, failing)
    assert count_tenders(session) == 0


def test_truncated_chain_links_farthest_notice_reached(session: Session) -> None:
    def partial(identifier: str) -> dict[str, Any] | None:
        notice = lookup(identifier)
        return notice if notice and notice["publication-number"] == FIRST_CHANGE else None

    outcome = save_notice(session, parse_notice(RAW[SECOND_CHANGE]), EVALUATION, partial)
    assert outcome.chain_complete is False
    assert outcome.tender.parent_publication_number == FIRST_CHANGE


def test_original_arriving_after_standalone_change_is_a_known_limit(session: Session) -> None:
    save(session, FIRST_CHANGE)
    save(session, ORIGINAL)
    # Limite documentato in dedup.py e ADR-014: restano due righe per la stessa gara.
    assert count_tenders(session) == 2
