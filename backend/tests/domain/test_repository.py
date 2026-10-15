"""Test di upsert_tender, get_tender e list_tenders (SQLite in memoria)."""

from datetime import UTC, date, datetime
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
from backend.tests.domain.conftest import make_tender


def _add(session: Session, number: str, score: int | None = None, **kw: Any) -> Tender:
    tender, _ = upsert_tender(session, make_tender(publication_number=number, **kw))
    tender.relevance_score = score
    session.flush()
    return tender


def _numbers(session: Session, **kw: Any) -> list[str]:
    return [t.publication_number for t in list_tenders(session, **kw).items]


def test_upsert_inserts_new_tender(session: Session) -> None:
    tender, created = upsert_tender(session, make_tender())
    assert created is True
    assert tender.id is not None
    assert tender.relevance_score is None
    assert tender.is_relevant is False
    assert tender.created_at is not None


def test_upsert_twice_does_not_duplicate_and_updates_fields(session: Session) -> None:
    first, _ = upsert_tender(session, make_tender())
    new_deadline = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    second, created = upsert_tender(session, make_tender(submission_deadline=new_deadline))
    assert created is False
    assert second.id == first.id
    assert second.submission_deadline == new_deadline
    assert session.query(Tender).count() == 1


def test_upsert_keeps_computed_fields(session: Session) -> None:
    tender, _ = upsert_tender(session, make_tender())
    tender.relevance_score, tender.is_relevant = 4, True
    upsert_tender(session, make_tender(title="Titolo aggiornato"))
    assert (tender.relevance_score, tender.is_relevant, tender.title) == (
        4,
        True,
        "Titolo aggiornato",
    )


def test_upsert_preserves_missing_value_as_null(session: Session) -> None:
    tender, _ = upsert_tender(session, make_tender(estimated_value=None, submission_deadline=None))
    assert tender.estimated_value is None
    assert tender.submission_deadline is None


def test_get_tender(session: Session) -> None:
    tender, _ = upsert_tender(session, make_tender())
    assert get_tender(session, tender.id) is tender
    assert get_tender(session, 9999) is None
    assert get_tender_by_publication_number(session, "000001-2026") is tender
    assert get_tender_by_publication_number(session, "nope") is None


def test_score_outside_1_5_is_rejected_by_database(session: Session) -> None:
    tender, _ = upsert_tender(session, make_tender())
    tender.relevance_score = 6
    with pytest.raises(IntegrityError):
        session.flush()


def test_list_default_order_score_desc_then_deadline_asc(session: Session) -> None:
    def d(day: int) -> datetime:
        return datetime(2026, 11, day, tzinfo=UTC)

    _add(session, "a", 3, submission_deadline=d(5))
    _add(session, "b", 5, submission_deadline=d(20))
    _add(session, "c", 5, submission_deadline=d(10))
    _add(session, "d", None)
    _add(session, "e", 3, submission_deadline=None)
    page = list_tenders(session)
    assert [t.publication_number for t in page.items] == ["c", "b", "a", "e", "d"]
    assert page.total == 5


def test_list_filter_min_score_and_is_relevant(session: Session) -> None:
    _add(session, "a", 2)
    t = _add(session, "b", 4)
    t.is_relevant = True
    assert _numbers(session, min_score=3) == ["b"]
    assert _numbers(session, is_relevant=True) == ["b"]
    assert list_tenders(session, is_relevant=False).total == 1


def test_list_filter_cpv_prefix(session: Session) -> None:
    _add(session, "it", 3, cpv_codes=["72000000", "30213000"])
    _add(session, "hw", 3, cpv_codes=["30213000"])
    _add(session, "none", 3, cpv_codes=[])
    assert _numbers(session, cpv="72") == ["it"]
    assert _numbers(session, cpv="72000000") == ["it"]
    assert list_tenders(session, cpv="302").total == 2
    assert list_tenders(session, cpv="9").total == 0
    with pytest.raises(ValueError):
        list_tenders(session, cpv="72%")


def test_list_filter_deadline_publication_and_value(session: Session) -> None:
    _add(
        session,
        "a",
        3,
        submission_deadline=datetime(2026, 11, 10, tzinfo=UTC),
        publication_date=date(2026, 10, 1),
        estimated_value=Decimal("100000"),
    )
    _add(
        session,
        "b",
        3,
        submission_deadline=datetime(2026, 12, 10, tzinfo=UTC),
        publication_date=date(2026, 10, 9),
        estimated_value=Decimal("900000"),
    )
    _add(session, "c", 3, submission_deadline=None, estimated_value=None)

    def numbers(**kw: Any) -> list[str]:
        return sorted(_numbers(session, **kw))

    assert numbers(deadline_from=datetime(2026, 12, 1, tzinfo=UTC)) == ["b"]
    assert numbers(deadline_to=datetime(2026, 11, 30, tzinfo=UTC)) == ["a"]
    assert numbers(publication_from=date(2026, 10, 5)) == ["b"]
    assert numbers(publication_to=date(2026, 10, 5)) == ["a", "c"]
    assert numbers(min_value=Decimal("500000")) == ["b"]
    assert numbers(max_value=Decimal("500000")) == ["a"]


def test_list_filter_text_query_is_case_insensitive_and_escapes_wildcards(
    session: Session,
) -> None:
    _add(session, "a", 3, title="Piattaforma CLOUD", description=None)
    _add(session, "b", 3, title="Altro", description="migrazione al cloud")
    _add(session, "c", 3, title="Altro", buyer_name="Cloud Srl")
    _add(session, "d", 3, title="100% pronto")
    assert list_tenders(session, q="cloud").total == 3
    assert _numbers(session, q="100%") == ["d"]
    assert list_tenders(session, q="%").total == 1
    assert list_tenders(session, q="   ").total == 4


def test_list_filter_report_status(session: Session) -> None:
    a = _add(session, "a", 3)
    b = _add(session, "b", 3)
    _add(session, "c", 3)
    session.add_all(
        [
            Report(tender=a, summary="s", status=ReportStatus.TO_REVIEW, ai_label="x"),
            Report(tender=b, summary="s", status=ReportStatus.VERIFIED, ai_label="x"),
        ]
    )
    session.flush()
    assert _numbers(session, report_status=ReportStatus.TO_REVIEW) == ["a"]
    assert list_tenders(session, report_status=ReportStatus.VERIFIED).total == 1


def test_report_is_unique_per_tender(session: Session) -> None:
    a = _add(session, "a", 3)
    session.add(Report(tender_id=a.id, summary="s", ai_label="x"))
    session.flush()
    session.add(Report(tender_id=a.id, summary="s2", ai_label="x"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_list_pagination(session: Session) -> None:
    for i in range(25):
        _add(session, f"n{i:02d}", 3)
    p1 = list_tenders(session, page=1, page_size=10)
    p3 = list_tenders(session, page=3, page_size=10)
    assert (len(p1.items), p1.total) == (10, 25)
    assert len(p3.items) == 5
    assert not {t.id for t in p1.items} & {t.id for t in p3.items}
    assert list_tenders(session, page=4, page_size=10).items == []


@pytest.mark.parametrize("kwargs", [{"page": 0}, {"page_size": 0}, {"page_size": 101}])
def test_list_rejects_invalid_pagination(session: Session, kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        list_tenders(session, **kwargs)


def test_list_other_sorts(session: Session) -> None:
    _add(session, "a", 3, publication_date=date(2026, 10, 1), estimated_value=Decimal("5"))
    _add(session, "b", 3, publication_date=date(2026, 10, 3), estimated_value=None)
    _add(session, "c", 3, publication_date=date(2026, 10, 2), estimated_value=Decimal("9"))
    assert _numbers(session, sort="publication_date_desc") == ["b", "c", "a"]
    assert _numbers(session, sort="value_desc") == ["c", "a", "b"]
    with pytest.raises(ValueError):
        list_tenders(session, sort="boh")  # type: ignore[arg-type]
