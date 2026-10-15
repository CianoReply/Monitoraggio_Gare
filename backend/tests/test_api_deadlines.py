"""Test di GET /deadlines (T3.5) con dati scelti ad hoc e orologio fisso. Senza rete.

Oggi (fisso) è il 15/10/2026, 14:00 a Roma.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from openapi_schema_validator import OAS31Validator, oas31_format_checker
from sqlalchemy import Engine, StaticPool, create_engine
from sqlalchemy.orm import Session

from backend.domain.database import create_session_factory
from backend.domain.models import Base
from backend.domain.repository import upsert_tender
from backend.domain.schemas import TenderEvaluation
from backend.tests.api_db import SEED_TODAY, make_app
from backend.tests.contract_utils import resolve
from backend.tests.domain.conftest import make_tender


def _at_noon(offset_days: int) -> datetime:
    """Mezzogiorno UTC (14:00 a Roma) del giorno SEED_TODAY + offset."""
    day = SEED_TODAY + timedelta(days=offset_days)
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)


def _engine(tenders: list[tuple[str, dict[str, Any], TenderEvaluation]]) -> Engine:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with create_session_factory(engine)() as session:
        _fill(session, tenders)
        session.commit()
    return engine


def _fill(session: Session, tenders: list[tuple[str, dict[str, Any], TenderEvaluation]]) -> None:
    for index, (title, fields, evaluation) in enumerate(tenders, start=1):
        number = f"{index:06d}-2026"
        data = {"publication_number": number, "ted_url": f"https://x.invalid/{number}"}
        upsert_tender(session, make_tender(title=title, **{**data, **fields}), evaluation)


RELEVANT = TenderEvaluation(3, True)

# (titolo, giorni da oggi, giorni_left attesi, urgenza attesa)
IN_RANGE = [
    ("oggi", 0, 0, "high"),
    ("tra 3 giorni", 3, 3, "high"),
    ("tra 4 giorni", 4, 4, "medium"),
    ("tra 7 giorni", 7, 7, "medium"),
    ("tra 8 giorni", 8, 8, "low"),
    ("tra 30 giorni", 30, 30, "low"),
]


@pytest.fixture(scope="module")
def client() -> TestClient:
    tenders: list[tuple[str, dict[str, Any], TenderEvaluation]] = [
        (title, {"submission_deadline": _at_noon(days)}, RELEVANT) for title, days, _, _ in IN_RANGE
    ]
    tenders += [
        ("tra 31 giorni", {"submission_deadline": _at_noon(31)}, RELEVANT),
        ("ieri", {"submission_deadline": _at_noon(-1)}, RELEVANT),
        ("5 giorni fa", {"submission_deadline": _at_noon(-5)}, RELEVANT),
        ("non rilevante", {"submission_deadline": _at_noon(2)}, TenderEvaluation(2, False)),
        (
            "scartata",
            {"submission_deadline": _at_noon(2)},
            TenderEvaluation(2, False, "CPV non IT"),
        ),
        ("senza scadenza", {"submission_deadline": None}, RELEVANT),
        # 22:30 UTC del 15/10 = 00:30 del 16/10 a Roma: manca 1 giorno, non 0.
        (
            "dopo mezzanotte a Roma",
            {"submission_deadline": datetime(2026, 10, 15, 22, 30, tzinfo=UTC)},
            RELEVANT,
        ),
    ]
    return TestClient(make_app(_engine(tenders)))


def _titles(client: TestClient, **params: Any) -> list[str]:
    response = client.get("/deadlines", params=params)
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


@pytest.mark.contract
def test_response_conforms_to_contract(client: TestClient, spec: dict) -> None:
    response = client.get("/deadlines")
    assert response.status_code == 200
    media = spec["paths"]["/deadlines"]["get"]["responses"]["200"]
    schema = resolve(spec, media)["content"]["application/json"]["schema"]
    validator = OAS31Validator(schema, format_checker=oas31_format_checker)
    assert [e.message for e in validator.iter_errors(response.json())] == []


def test_default_range_is_today_plus_30_days_only_relevant_with_deadline(
    client: TestClient,
) -> None:
    titles = _titles(client)
    assert titles == [
        "oggi",
        "dopo mezzanotte a Roma",
        "tra 3 giorni",
        "tra 4 giorni",
        "tra 7 giorni",
        "tra 8 giorni",
        "tra 30 giorni",
    ]
    for excluded in ("tra 31 giorni", "ieri", "5 giorni fa", "non rilevante", "scartata"):
        assert excluded not in titles
    assert "senza scadenza" not in titles


def test_items_are_ordered_by_deadline(client: TestClient) -> None:
    items = client.get("/deadlines").json()["items"]
    stamps = [datetime.fromisoformat(i["submission_deadline"]) for i in items]
    assert stamps == sorted(stamps)


@pytest.mark.parametrize(("title", "days", "days_left", "urgency"), IN_RANGE)
def test_days_left_and_urgency(
    client: TestClient, title: str, days: int, days_left: int, urgency: str
) -> None:
    item = next(i for i in client.get("/deadlines").json()["items"] if i["title"] == title)
    assert item["days_left"] == days_left
    assert item["urgency"] == urgency
    deadline = datetime.fromisoformat(item["submission_deadline"])
    assert deadline.utcoffset() is not None
    assert deadline == _at_noon(days)


def test_days_left_uses_rome_calendar_day(client: TestClient) -> None:
    item = next(
        i
        for i in client.get("/deadlines").json()["items"]
        if i["title"] == "dopo mezzanotte a Roma"
    )
    assert item["days_left"] == 1
    assert item["urgency"] == "high"
    assert datetime.fromisoformat(item["submission_deadline"]).isoformat().endswith("+02:00")


def test_item_fields_come_from_the_tender(client: TestClient) -> None:
    item = client.get("/deadlines").json()["items"][0]
    assert set(item) == {
        "tender_id",
        "publication_number",
        "title",
        "buyer_name",
        "submission_deadline",
        "relevance_score",
        "days_left",
        "urgency",
    }
    tender = client.get(f"/tenders/{item['tender_id']}").json()
    assert item["publication_number"] == tender["publication_number"]
    assert item["buyer_name"] == tender["buyer_name"]
    assert item["relevance_score"] == tender["relevance_score"]


def test_explicit_range_is_inclusive(client: TestClient) -> None:
    today = SEED_TODAY
    found = _titles(
        client,
        **{
            "from": (today + timedelta(days=3)).isoformat(),
            "to": (today + timedelta(days=7)).isoformat(),
        },
    )
    assert found == ["tra 3 giorni", "tra 4 giorni", "tra 7 giorni"]


def test_single_day_range(client: TestClient) -> None:
    day = SEED_TODAY.isoformat()
    assert _titles(client, **{"from": day, "to": day}) == ["oggi"]


def test_past_deadlines_are_returned_with_zero_days_left(client: TestClient) -> None:
    items = client.get(
        "/deadlines",
        params={
            "from": (SEED_TODAY - timedelta(days=10)).isoformat(),
            "to": SEED_TODAY.isoformat(),
        },
    ).json()["items"]
    by_title = {i["title"]: i for i in items}
    assert {"5 giorni fa", "ieri", "oggi"} <= set(by_title)
    for title in ("5 giorni fa", "ieri", "oggi"):
        assert by_title[title]["days_left"] == 0
        assert by_title[title]["urgency"] == "high"


def test_range_without_results_is_empty_list(client: TestClient) -> None:
    far = (SEED_TODAY + timedelta(days=200)).isoformat()
    response = client.get("/deadlines", params={"from": far, "to": far})
    assert response.status_code == 200
    assert response.json() == {"items": []}


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-11-10", "to": "2026-11-01"},
        {"from": "non-una-data"},
        {"to": "2026-13-45"},
        {"from": "2027-06-01"},  # `to` assente = oggi + 30: precede `from`
    ],
)
def test_invalid_ranges_return_422(client: TestClient, params: dict) -> None:
    response = client.get("/deadlines", params=params)
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error", "message"}
    assert body["error"] == "validation_error"


def test_more_than_one_page_of_deadlines_is_returned_completely() -> None:
    many = [
        (f"gara {i:03d}", {"submission_deadline": _at_noon(1 + i % 20)}, RELEVANT)
        for i in range(130)
    ]
    items = TestClient(make_app(_engine(many))).get("/deadlines").json()["items"]
    assert len(items) == 130
    assert len({i["tender_id"] for i in items}) == 130


def test_today_comes_from_the_clock_in_rome() -> None:
    # Alle 23:30 UTC del 15/10 a Roma è già il 16/10: "oggi" è il 16 e la scadenza del 15 non c'è.
    late = datetime(2026, 10, 15, 23, 30, tzinfo=UTC)
    tenders = [("del 15", {"submission_deadline": _at_noon(0)}, RELEVANT)]
    client = TestClient(make_app(_engine(tenders), now=late))
    assert client.get("/deadlines").json() == {"items": []}
    day = date(2026, 10, 15).isoformat()
    assert [i["title"] for i in client.get("/deadlines", params={"from": day}).json()["items"]] == [
        "del 15"
    ]
