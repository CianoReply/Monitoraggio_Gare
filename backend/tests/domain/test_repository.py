"""Test di upsert_tender, get_tender e list_tenders (SQLite in memoria)."""

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain.models import Report, ReportStatus, Tender
from backend.domain.repository import (
    get_tender,
    get_tender_by_publication_number,
    list_tenders,
    upsert_tender,
)
from backend.domain.schemas import TenderEvaluation
from backend.tests.domain.conftest import make_tender

ROME_WINTER = timezone(timedelta(hours=1))  # Europe/Rome a novembre (CET)


def _add(
    session: Session, number: str, score: int = 3, discard: str | None = None, **kw: Any
) -> Tender:
    evaluation = TenderEvaluation(score, discard is None and score >= 3, discard)
    tender, _ = upsert_tender(session, make_tender(publication_number=number, **kw), evaluation)
    return tender


def _numbers(session: Session, **kw: Any) -> list[str]:
    return [row.tender.publication_number for row in list_tenders(session, **kw).items]


def test_upsert_inserts_new_evaluated_tender(session: Session) -> None:
    tender, created = upsert_tender(session, make_tender(), TenderEvaluation(4, True))
    assert created is True
    assert tender.id is not None
    assert (tender.relevance_score, tender.is_relevant, tender.discard_reason) == (4, True, None)
    assert tender.created_at is not None


def test_upsert_twice_does_not_duplicate_and_rewrites_evaluation(session: Session) -> None:
    first, _ = upsert_tender(session, make_tender(), TenderEvaluation(4, True))
    new_deadline = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    second, created = upsert_tender(
        session,
        make_tender(submission_deadline=new_deadline, title="Titolo aggiornato"),
        TenderEvaluation(1, False, "CPV non pertinente"),
    )
    assert created is False
    assert second.id == first.id
    assert second.submission_deadline == new_deadline
    assert second.title == "Titolo aggiornato"
    assert (second.relevance_score, second.is_relevant, second.discard_reason) == (
        1,
        False,
        "CPV non pertinente",
    )
    assert session.query(Tender).count() == 1


def test_upsert_stores_deadline_in_utc(session: Session) -> None:
    deadline = datetime(2026, 11, 20, 12, 0, tzinfo=ROME_WINTER)
    tender, _ = upsert_tender(
        session, make_tender(submission_deadline=deadline), TenderEvaluation(3, True)
    )
    assert tender.submission_deadline == datetime(2026, 11, 20, 11, 0, tzinfo=UTC)


def test_upsert_preserves_missing_value_as_null(session: Session) -> None:
    tender = _add(session, "a", estimated_value=None, submission_deadline=None)
    assert tender.estimated_value is None
    assert tender.submission_deadline is None


def test_evaluation_is_validated() -> None:
    with pytest.raises(ValueError):
        TenderEvaluation(6, False)
    with pytest.raises(ValueError):
        TenderEvaluation(0, False)
    with pytest.raises(ValueError):
        TenderEvaluation(4, True, "scartata")


def test_get_tender(session: Session) -> None:
    tender = _add(session, "000001-2026")
    assert get_tender(session, tender.id) is tender
    assert get_tender(session, 9999) is None
    assert get_tender_by_publication_number(session, "000001-2026") is tender
    assert get_tender_by_publication_number(session, "nope") is None


def test_database_requires_score_between_1_and_5(session: Session) -> None:
    tender = _add(session, "a")
    tender.relevance_score = 6
    with pytest.raises(IntegrityError):
        session.flush()


def test_list_default_order_relevance_then_deadline_nulls_last(session: Session) -> None:
    def d(day: int) -> datetime:
        return datetime(2026, 11, day, tzinfo=UTC)

    _add(session, "a", 3, submission_deadline=d(5))
    _add(session, "b", 5, submission_deadline=d(20))
    _add(session, "c", 5, submission_deadline=d(10))
    _add(session, "d", 5, submission_deadline=None)
    _add(session, "e", 3, submission_deadline=None)
    page = list_tenders(session)
    assert [r.tender.publication_number for r in page.items] == ["c", "b", "d", "a", "e"]
    assert page.total == 5


def test_list_sort_deadline_and_published(session: Session) -> None:
    _add(session, "a", publication_date=date(2026, 10, 1), submission_deadline=None)
    _add(
        session,
        "b",
        publication_date=date(2026, 10, 3),
        submission_deadline=datetime(2026, 12, 1, tzinfo=UTC),
    )
    _add(
        session,
        "c",
        publication_date=date(2026, 10, 2),
        submission_deadline=datetime(2026, 11, 1, tzinfo=UTC),
    )
    assert _numbers(session, sort="deadline") == ["c", "b", "a"]
    assert _numbers(session, sort="published") == ["b", "c", "a"]
    with pytest.raises(ValueError):
        list_tenders(session, sort="value_desc")  # type: ignore[arg-type]


def test_list_excludes_discarded_unless_requested(session: Session) -> None:
    _add(session, "ok", 4)
    _add(session, "bad", 1, discard="CPV non pertinente")
    assert _numbers(session) == ["ok"]
    assert sorted(_numbers(session, include_discarded=True)) == ["bad", "ok"]
    assert list_tenders(session, include_discarded=True).total == 2


def test_list_filter_min_score_and_internal_is_relevant(session: Session) -> None:
    _add(session, "a", 2)
    _add(session, "b", 4)
    assert _numbers(session, min_score=3) == ["b"]
    assert _numbers(session, is_relevant=True) == ["b"]
    assert _numbers(session, is_relevant=False) == ["a"]


def test_list_filter_cpv_prefix(session: Session) -> None:
    _add(session, "it", cpv_codes=["72000000", "30213000"])
    _add(session, "hw", cpv_codes=["30213000"])
    _add(session, "none", cpv_codes=[])
    assert _numbers(session, cpv="72") == ["it"]
    assert _numbers(session, cpv="72000000") == ["it"]
    assert list_tenders(session, cpv="302").total == 2
    assert list_tenders(session, cpv="97").total == 0


@pytest.mark.parametrize("cpv", ["7", "72%", "720000000", "ab", ""])
def test_list_rejects_invalid_cpv(session: Session, cpv: str) -> None:
    with pytest.raises(ValueError):
        list_tenders(session, cpv=cpv)


def test_list_deadline_range_covers_whole_day_in_rome(session: Session) -> None:
    # Le ore 23:30 e 00:30 di Roma cadono in giorni UTC diversi dal giorno di Roma.
    _add(session, "late20", submission_deadline=datetime(2026, 11, 20, 23, 30, tzinfo=ROME_WINTER))
    _add(session, "early21", submission_deadline=datetime(2026, 11, 21, 0, 30, tzinfo=ROME_WINTER))
    _add(session, "early20", submission_deadline=datetime(2026, 11, 20, 0, 30, tzinfo=ROME_WINTER))
    _add(session, "late19", submission_deadline=datetime(2026, 11, 19, 23, 30, tzinfo=ROME_WINTER))
    _add(session, "nodeadline", submission_deadline=None)
    day = date(2026, 11, 20)
    assert sorted(_numbers(session, deadline_from=day, deadline_to=day)) == ["early20", "late20"]
    assert sorted(_numbers(session, deadline_from=day)) == ["early20", "early21", "late20"]
    assert sorted(_numbers(session, deadline_to=day)) == ["early20", "late19", "late20"]


def test_list_filter_value_and_internal_publication_range(session: Session) -> None:
    _add(session, "a", publication_date=date(2026, 10, 1), estimated_value=Decimal("100000"))
    _add(session, "b", publication_date=date(2026, 10, 9), estimated_value=Decimal("900000"))
    _add(session, "c", estimated_value=None)
    assert _numbers(session, min_value=Decimal("500000")) == ["b"]
    assert _numbers(session, max_value=Decimal("500000")) == ["a"]
    assert _numbers(session, publication_from=date(2026, 10, 5)) == ["b"]
    assert sorted(_numbers(session, publication_to=date(2026, 10, 5))) == ["a", "c"]


def test_list_filter_text_query_is_case_insensitive_and_escapes_wildcards(
    session: Session,
) -> None:
    _add(session, "a", title="Piattaforma CLOUD", description=None)
    _add(session, "b", title="Altro", description="migrazione al cloud")
    _add(session, "c", title="Altro", buyer_name="Cloud Srl")
    _add(session, "d", title="100% pronto")
    assert list_tenders(session, q="cloud").total == 3
    assert _numbers(session, q="100%") == ["d"]
    assert list_tenders(session, q="%").total == 1
    assert list_tenders(session, q="   ").total == 4


def test_list_derives_report_status_in_items_and_filter(session: Session) -> None:
    a = _add(session, "a", 5)
    b = _add(session, "b", 4)
    _add(session, "c", 3)
    session.add_all(
        [
            Report(tender=a, summary="s", status=ReportStatus.TO_REVIEW, ai_label="x"),
            Report(tender=b, summary="s", status=ReportStatus.VERIFIED, ai_label="x"),
        ]
    )
    session.flush()
    rows = list_tenders(session).items
    assert [(r.tender.publication_number, r.report_status) for r in rows] == [
        ("a", "to_review"),
        ("b", "verified"),
        ("c", "none"),
    ]
    assert _numbers(session, report_status="to_review") == ["a"]
    assert _numbers(session, report_status="verified") == ["b"]
    assert _numbers(session, report_status="none") == ["c"]
    assert list_tenders(session, report_status="none").total == 1
    with pytest.raises(ValueError):
        list_tenders(session, report_status="boh")  # type: ignore[arg-type]


def test_report_is_unique_per_tender(session: Session) -> None:
    a = _add(session, "a")
    session.add(Report(tender_id=a.id, summary="s", ai_label="x"))
    session.flush()
    session.add(Report(tender_id=a.id, summary="s2", ai_label="x"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_list_pagination(session: Session) -> None:
    for i in range(25):
        _add(session, f"n{i:02d}")
    p1 = list_tenders(session, page=1, page_size=10)
    p3 = list_tenders(session, page=3, page_size=10)
    assert (len(p1.items), p1.total) == (10, 25)
    assert len(p3.items) == 5
    assert not {r.tender.id for r in p1.items} & {r.tender.id for r in p3.items}
    beyond = list_tenders(session, page=4, page_size=10)
    assert (beyond.items, beyond.total) == ([], 25)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"min_score": 0},
        {"min_score": 6},
        {"min_value": Decimal("-1")},
        {"max_value": Decimal("-1")},
        {"min_value": Decimal("10"), "max_value": Decimal("5")},
        {"deadline_from": date(2026, 11, 2), "deadline_to": date(2026, 11, 1)},
        {"q": "x" * 201},
    ],
)
def test_list_rejects_invalid_parameters(session: Session, kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        list_tenders(session, **kwargs)


def test_list_accepts_equal_bounds_and_max_length_query(session: Session) -> None:
    list_tenders(session, min_value=Decimal("5"), max_value=Decimal("5"), q="x" * 200)
    list_tenders(session, deadline_from=date(2026, 11, 1), deadline_to=date(2026, 11, 1))
