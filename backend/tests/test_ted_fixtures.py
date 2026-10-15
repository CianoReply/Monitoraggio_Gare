"""Test delle fixture reali di TED raccolte in T1.1.

Fissano le osservazioni scritte in docs/TED_API_NOTES.md, così un cambio delle fixture
che le smentisce fa fallire i test invece di passare inosservato.
"""

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
IT_CPV_PREFIXES = ("72", "48", "302", "324", "642")


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def daily() -> dict[str, Any]:
    return load("ted_search_it_2026-10-14.json")


@pytest.fixture(scope="module")
def changes() -> dict[str, Any]:
    return load("ted_search_it_changes_2026-10.json")


@pytest.fixture(scope="module")
def predecessors() -> dict[str, Any]:
    return load("ted_lookup_change_predecessors.json")


def test_daily_search_returns_italian_it_notices(daily: dict[str, Any]) -> None:
    response = daily["response"]
    assert response["totalNoticeCount"] == len(response["notices"]) > 0
    for notice in response["notices"]:
        assert notice["buyer-country"] == ["ITA"]
        assert any(cpv.startswith(IT_CPV_PREFIXES) for cpv in notice["classification-cpv"])
        assert notice["publication-date"].startswith("2026-10-14")


def test_daily_request_respects_fields_per_page_limit(daily: dict[str, Any]) -> None:
    request = daily["request"]
    assert len(request["fields"]) * request["limit"] <= 10_000


def test_texts_are_objects_by_language(daily: dict[str, Any]) -> None:
    notice = daily["response"]["notices"][0]
    assert isinstance(notice["title-proc"]["ita"], str)
    assert isinstance(notice["buyer-name"]["ita"], list)


def test_tender_deadline_differs_from_bt13_deadline(daily: dict[str, Any]) -> None:
    notice = next(
        n for n in daily["response"]["notices"] if n["publication-number"] == "707611-2026"
    )
    assert notice["deadline-receipt-tender-date-lot"] == ["2026-11-16+02:00"]
    assert notice["deadline-date-lot"] == ["2026-11-06+02:00"]


def test_results_have_no_tender_deadline(daily: dict[str, Any]) -> None:
    results = [n for n in daily["response"]["notices"] if n["notice-type"].startswith("can-")]
    assert results
    assert all("deadline-receipt-tender-date-lot" not in n for n in results)


def test_change_notices_keep_notice_type_and_reference_predecessor(
    changes: dict[str, Any], predecessors: dict[str, Any]
) -> None:
    known = {n["notice-identifier"] for n in predecessors["response"]["notices"]}
    for notice in changes["response"]["notices"]:
        assert notice["notice-type"] == "cn-standard"
        reference = notice["change-notice-version-identifier"]
        assert reference.rsplit("-", 1)[0] in known


def test_change_chain_reaches_original(predecessors: dict[str, Any]) -> None:
    by_id = {n["notice-identifier"]: n for n in predecessors["response"]["notices"]}
    notice = by_id["68d34303-2d11-45ec-ae35-19a735ee975d"]  # 566426-2026, a sua volta una modifica
    while "change-notice-version-identifier" in notice:
        notice = by_id[notice["change-notice-version-identifier"].rsplit("-", 1)[0]]
    assert notice["publication-number"] == "437009-2026"
