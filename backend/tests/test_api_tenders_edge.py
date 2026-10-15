"""Casi limite di GET /tenders con dati scelti ad hoc (fuso, ricerca, CPV) e dipendenze."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, StaticPool, create_engine, select
from sqlalchemy.orm import Session

from backend.api import deps
from backend.api.tenders import _aware, tender_from_row
from backend.domain.database import create_session_factory
from backend.domain.models import Base, Tender
from backend.domain.repository import TenderRow, upsert_tender
from backend.domain.schemas import TenderEvaluation
from backend.tests.api_db import make_app
from backend.tests.domain.conftest import make_tender


def _engine(tenders: list[dict[str, Any]]) -> Engine:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as session:
        for index, fields in enumerate(tenders, start=1):
            number = f"{index:06d}-2026"
            data = {"publication_number": number, "ted_url": f"https://x.invalid/{number}"}
            upsert_tender(session, make_tender(**{**data, **fields}), TenderEvaluation(3, True))
        session.commit()
    return engine


def _client(tenders: list[dict[str, Any]]) -> TestClient:
    return TestClient(make_app(_engine(tenders)))


def _titles(client: TestClient, **params: Any) -> set[str]:
    response = client.get("/tenders", params={"page_size": 100, **params})
    assert response.status_code == 200, response.text
    return {item["title"] for item in response.json()["items"]}


# --- Fuso orario ------------------------------------------------------------------------


def _at(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


DEADLINES = {
    "winter": _at(2026, 11, 20, 11, 0),  # Roma 12:00 +01:00
    "summer": _at(2026, 7, 15, 10, 0),  # Roma 12:00 +02:00
    "after-midnight": _at(2026, 10, 20, 22, 30),  # Roma 21/10 00:30
    "midnight": _at(2026, 10, 20, 22, 0),  # Roma 21/10 00:00 esatto
    "last-second": _at(2026, 10, 21, 21, 59, 59),  # Roma 21/10 23:59:59
    "next-midnight": _at(2026, 10, 21, 22, 0),  # Roma 22/10 00:00 esatto
}


@pytest.fixture(scope="module")
def tz_client() -> TestClient:
    return _client([{"title": name, "submission_deadline": dt} for name, dt in DEADLINES.items()])


def test_deadline_is_returned_in_rome_with_same_instant_and_offset(tz_client: TestClient) -> None:
    items = tz_client.get("/tenders", params={"page_size": 100}).json()["items"]
    by_title = {item["title"]: item["submission_deadline"] for item in items}
    expected_offset = {"winter": 3600, "summer": 7200, "after-midnight": 7200, "midnight": 7200}
    for name, instant in DEADLINES.items():
        returned = datetime.fromisoformat(by_title[name])
        assert returned == instant, name
        if name in expected_offset:
            offset = returned.utcoffset()
            assert offset is not None
            assert offset.total_seconds() == expected_offset[name], name
    assert by_title["winter"] == "2026-11-20T12:00:00+01:00"
    assert by_title["summer"] == "2026-07-15T12:00:00+02:00"


def test_deadline_from_includes_tender_that_is_already_next_day_in_rome(
    tz_client: TestClient,
) -> None:
    found = _titles(tz_client, deadline_from="2026-10-21")
    assert {"after-midnight", "midnight", "last-second", "next-midnight"} <= found
    assert "summer" not in found


def test_deadline_to_excludes_tender_that_is_already_next_day_in_rome(
    tz_client: TestClient,
) -> None:
    found = _titles(tz_client, deadline_to="2026-10-20")
    assert "after-midnight" not in found  # 22:30Z = 21/10 a Roma
    assert "midnight" not in found  # mezzanotte esatta di Roma del 21/10
    assert "summer" in found


def test_deadline_range_for_single_rome_day(tz_client: TestClient) -> None:
    found = _titles(tz_client, deadline_from="2026-10-21", deadline_to="2026-10-21")
    assert found == {"after-midnight", "midnight", "last-second"}


def test_deadline_at_next_rome_midnight_belongs_to_next_day(tz_client: TestClient) -> None:
    assert "next-midnight" not in _titles(tz_client, deadline_to="2026-10-21")
    assert "last-second" not in _titles(tz_client, deadline_from="2026-10-22")
    assert "next-midnight" in _titles(tz_client, deadline_from="2026-10-22")


# --- Ricerca testuale -------------------------------------------------------------------------

SEARCH_TENDERS = [
    {"title": "Alpha titolo", "description": "niente", "buyer_name": "Ente Uno"},
    {"title": "Titolo due", "description": "contiene Bravo qui", "buyer_name": "Ente Due"},
    {"title": "Titolo tre", "description": None, "buyer_name": "Ente Charlie SpA"},
    {"title": "Sconto 50% garantito", "description": None, "buyer_name": "Ente Quattro"},
    {"title": "Codice a_b interno", "description": None, "buyer_name": "Ente Cinque"},
    {"title": "Titolo sei", "description": "nulla", "buyer_name": "Ente Sei"},
]


@pytest.fixture(scope="module")
def search_client() -> TestClient:
    return _client(SEARCH_TENDERS)


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("alpha", {"Alpha titolo"}),
        ("BRAVO", {"Titolo due"}),
        ("charlie", {"Titolo tre"}),
    ],
)
def test_q_matches_title_description_or_buyer_only(
    search_client: TestClient, term: str, expected: set[str]
) -> None:
    assert _titles(search_client, q=term) == expected


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("%", {"Sconto 50% garantito"}),
        ("_", {"Codice a_b interno"}),
        ("a_b", {"Codice a_b interno"}),
    ],
)
def test_q_wildcards_are_matched_literally(
    search_client: TestClient, term: str, expected: set[str]
) -> None:
    assert _titles(search_client, q=term) == expected
    assert len(expected) < len(SEARCH_TENDERS)


# --- CPV ---------------------------------------------------------------------------------------

CPV_SETS = [["72212000"], ["48722000"], ["22000000", "72000000"], ["50312000", "72267000"], []]


@pytest.fixture(scope="module")
def cpv_client() -> TestClient:
    return _client([{"title": f"gara {i}", "cpv_codes": cpv} for i, cpv in enumerate(CPV_SETS)])


@pytest.mark.parametrize("prefix", ["22", "72", "722", "48", "72212000", "50312000", "99"])
def test_cpv_matches_only_prefix_of_a_code(cpv_client: TestClient, prefix: str) -> None:
    expected = {
        f"gara {i}"
        for i, codes in enumerate(CPV_SETS)
        if any(code.startswith(prefix) for code in codes)
    }
    assert _titles(cpv_client, cpv=prefix) == expected


def test_cpv_middle_part_does_not_match(cpv_client: TestClient) -> None:
    # "48722000" e "72212000" contengono "22" solo al centro: il prefisso "22" trova solo
    # la gara con il codice "22000000".
    assert _titles(cpv_client, cpv="22") == {"gara 2"}
    assert _titles(cpv_client, cpv="7221") == {"gara 0"}


# --- Importi non finiti --------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["inf", "-inf", "nan", "Infinity"])
@pytest.mark.parametrize("name", ["min_value", "max_value"])
def test_non_finite_values_return_422(search_client: TestClient, name: str, value: str) -> None:
    response = search_client.get("/tenders", params={name: value})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


# --- Dipendenze e conversione -----------------------------------------------------------------


def test_get_session_uses_database_url_and_closes_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    deps._session_factory.cache_clear()
    try:
        generator: Iterator[Session] = deps.get_session()
        session = next(generator)
        assert isinstance(session, Session)
        assert session.execute(select(1)).scalar() == 1
        assert session.in_transaction()
        with pytest.raises(StopIteration):
            next(generator)
        assert not session.in_transaction()
    finally:
        deps._session_factory.cache_clear()


def test_get_session_without_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    deps._session_factory.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            next(deps.get_session())
    finally:
        deps._session_factory.cache_clear()


def test_session_factory_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    deps._session_factory.cache_clear()
    try:
        assert deps._session_factory() is deps._session_factory()
    finally:
        deps._session_factory.cache_clear()


def test_aware_adds_utc_to_naive_and_keeps_aware() -> None:
    naive = datetime(2026, 10, 15, 9, 30)
    assert _aware(naive) == datetime(2026, 10, 15, 9, 30, tzinfo=UTC)
    assert _aware(naive).utcoffset() == timedelta(0)
    rome = datetime(2026, 10, 15, 11, 30, tzinfo=timezone(timedelta(hours=2)))
    assert _aware(rome) is rome


def _orm_tender(deadline: datetime | None, created: datetime) -> Tender:
    return Tender(
        id=1,
        publication_number="000001-2026",
        title="t",
        description=None,
        buyer_name="b",
        buyer_city=None,
        cpv_codes=["72000000"],
        notice_type="n",
        estimated_value=Decimal("1500.50"),
        currency="EUR",
        publication_date=created.date(),
        submission_deadline=deadline,
        ted_url="https://x.invalid/1",
        documents_url=None,
        relevance_score=3,
        is_relevant=True,
        discard_reason=None,
        parent_publication_number=None,
        created_at=created,
        updated_at=created,
    )


def test_tender_from_row_converts_naive_datetimes_as_utc() -> None:
    naive_deadline = datetime(2026, 11, 20, 11, 0)  # come lo restituisce SQLite
    row = TenderRow(_orm_tender(naive_deadline, datetime(2026, 10, 1, 8, 0)), "to_review")
    tender = tender_from_row(row)
    assert tender.submission_deadline is not None
    assert tender.submission_deadline.isoformat() == "2026-11-20T12:00:00+01:00"
    assert tender.created_at.isoformat() == "2026-10-01T08:00:00+00:00"
    assert tender.report_status == "to_review"
    assert tender.estimated_value == 1500.5


def test_tender_from_row_converts_aware_datetimes_and_keeps_missing_deadline() -> None:
    aware = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    with_deadline = tender_from_row(TenderRow(_orm_tender(aware, aware), "none"))
    assert with_deadline.submission_deadline is not None
    assert with_deadline.submission_deadline.isoformat() == "2026-07-15T12:00:00+02:00"
    without = tender_from_row(TenderRow(_orm_tender(None, aware), "none"))
    assert without.submission_deadline is None
