"""Test del parser TED (T1.3): fixture reali di T1.1, nessuna rete."""

import copy
import json
import logging
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from backend.domain.schemas import TenderCreate
from backend.ingestion.parser import (
    MISSING_BUYER,
    MISSING_TITLE,
    NoticeParseError,
    as_list,
    change_reference,
    combine_deadline,
    earliest_deadline,
    estimated_value,
    first_value,
    is_change_notice,
    is_http_url,
    normalize_cpv_codes,
    normalize_currency,
    notice_url,
    parse_amount,
    parse_notice,
    parse_notices,
    parse_ted_date,
    pick_first_text,
    pick_text,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE_FILES = sorted(FIXTURES.glob("ted_*.json"))
CEST = timezone(timedelta(hours=2))
CET = timezone(timedelta(hours=1))


def notices(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["response"]["notices"]


def notice(publication_number: str) -> dict[str, Any]:
    for path in FIXTURE_FILES:
        for raw in notices(path.name):
            if raw["publication-number"] == publication_number:
                return copy.deepcopy(raw)
    raise KeyError(publication_number)


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_all_fixtures_convert_without_errors(path: Path) -> None:
    raws = notices(path.name)
    tenders = [parse_notice(raw) for raw in raws]
    assert len(tenders) == len(raws)
    assert all(isinstance(t, TenderCreate) for t in tenders)


def test_parse_notice_maps_a_real_competition_notice() -> None:
    raw = notice("707611-2026")
    tender = parse_notice(raw)
    assert tender.publication_number == "707611-2026"
    assert tender.title.startswith("Affidamento del servizio di gestione degli atti")
    assert tender.buyer_name == "Comune di Pizzo"
    assert tender.buyer_city == "Pizzo Calabro"
    assert tender.cpv_codes == ["72500000"]
    assert tender.notice_type == "cn-standard"
    assert tender.estimated_value == Decimal("293278.68")
    assert tender.currency == "EUR"
    assert tender.publication_date == date(2026, 10, 14)
    # scadenza offerte (BT-131), non la scadenza per le richieste di informazioni (BT-13)
    assert tender.submission_deadline == datetime(2026, 11, 16, 12, 0, tzinfo=CEST)
    assert tender.ted_url == "https://ted.europa.eu/it/notice/-/detail/707611-2026"
    assert tender.documents_url == "https://pizzo.tuttogare.it/gare/dettaglio.php?codice=249"
    assert tender.parent_publication_number is None
    assert tender.raw_data == raw


def test_notice_without_amount_and_deadline_gives_nulls(caplog: pytest.LogCaptureFixture) -> None:
    raw = notice("707611-2026")
    for key in list(raw):
        if key.startswith(("estimated-value", "deadline")):
            del raw[key]
    with caplog.at_level(logging.WARNING):
        tender = parse_notice(raw)
    assert tender.estimated_value is None
    assert tender.currency is None
    assert tender.submission_deadline is None
    assert "estimated-value" in caplog.text and "deadline-receipt-tender" in caplog.text


def test_result_notice_has_no_deadline() -> None:
    tender = parse_notice(notice("707979-2026"))
    assert tender.notice_type == "can-standard"
    assert tender.submission_deadline is None


def test_parent_publication_number_is_passed_through() -> None:
    tender = parse_notice(notice("687833-2026"), parent_publication_number="437009-2026")
    assert tender.parent_publication_number == "437009-2026"


def test_missing_texts_use_placeholders() -> None:
    raw = notice("707611-2026")
    for key in ("title-proc", "notice-title", "title-lot", "buyer-name", "organisation-name-buyer"):
        raw.pop(key)
    tender = parse_notice(raw)
    assert tender.title == MISSING_TITLE
    assert tender.buyer_name == MISSING_BUYER


@pytest.mark.parametrize("key", ["publication-number", "publication-date"])
def test_notice_without_identity_raises_parse_error(key: str) -> None:
    raw = notice("707611-2026")
    del raw[key]
    with pytest.raises(NoticeParseError):
        parse_notice(raw)


def test_parse_notices_skips_unusable_notices(caplog: pytest.LogCaptureFixture) -> None:
    good = notice("707611-2026")
    bad = notice("708163-2026")
    del bad["publication-number"]
    with caplog.at_level(logging.WARNING):
        tenders = parse_notices([good, bad, {"publication-number": "x", "publication-date": "bad"}])
    assert [t.publication_number for t in tenders] == ["707611-2026"]
    assert "Avviso saltato" in caplog.text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"ita": "Gara", "eng": "Tender"}, "Gara"),
        ({"eng": "Tender", "deu": "Ausschreibung"}, "Tender"),
        ({"deu": "Ausschreibung"}, "Ausschreibung"),
        ({"mul": ["Firenze"]}, "Firenze"),
        ({"ita": ["  "], "eng": "Tender"}, "Tender"),
        (["a", "a", "b"], "a b"),
        ("  testo ", "testo"),
        (None, None),
        ({}, None),
        (42, None),
    ],
)
def test_pick_text(value: Any, expected: str | None) -> None:
    assert pick_text(value) == expected


def test_pick_first_text_keeps_first_value() -> None:
    assert pick_first_text({"ita": ["Ente A", "Ente B"]}) == "Ente A"
    assert pick_first_text(["Roma", "Milano"]) == "Roma"
    assert pick_first_text(None) is None


def test_first_value_and_as_list() -> None:
    assert first_value(["a", "b"]) == "a"
    assert first_value([]) is None
    assert first_value("a") == "a"
    assert as_list(None) == []
    assert as_list("a") == ["a"]
    assert as_list(["a"]) == ["a"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-14+02:00", date(2026, 10, 14)),
        (["2026-10-14"], date(2026, 10, 14)),
        ("14/10/2026", None),
        ("2026", None),
        (None, None),
    ],
)
def test_parse_ted_date(value: Any, expected: date | None) -> None:
    assert parse_ted_date(value) == expected


@pytest.mark.parametrize(
    ("day", "clock", "expected"),
    [
        ("2026-11-23+01:00", "10:00:00+01:00", datetime(2026, 11, 23, 10, tzinfo=CET)),
        ("2026-10-20+02:00", None, datetime(2026, 10, 20, 23, 59, 59, tzinfo=CEST)),
        ("2026-10-20+02:00", "09:30:00Z", datetime(2026, 10, 20, 9, 30, tzinfo=UTC)),
        ("2026-10-20", "09:30:00", None),  # senza fuso: scartata
        ("non-una-data", "09:30:00+02:00", None),
        ("2026-10-20+02:00", "25:00:00+02:00", None),
        ("2026-10-20+99:00", None, None),
        (None, None, None),
    ],
)
def test_combine_deadline(day: Any, clock: Any, expected: datetime | None) -> None:
    assert combine_deadline(day, clock) == expected


def test_earliest_deadline_picks_nearest_lot() -> None:
    raw = {
        "deadline-receipt-tender-date-lot": ["2026-11-20+01:00", "2026-11-13+01:00", "bad"],
        "deadline-receipt-tender-time-lot": ["12:00:00+01:00", "13:00:00+01:00"],
    }
    assert earliest_deadline(raw) == datetime(2026, 11, 13, 13, tzinfo=CET)
    assert earliest_deadline({}) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("293278.68", Decimal("293278.68")),
        ("8571100.00000000", Decimal("8571100.00")),
        (2664750, Decimal("2664750.00")),
        ("-1", None),
        ("abc", None),
        ("NaN", None),
        ("1e30", None),
        ("99999999999999999", None),
        ("9999999999999999.99", Decimal("9999999999999999.99")),
        (True, None),
        (None, None),
    ],
)
def test_parse_amount(value: Any, expected: Decimal | None) -> None:
    assert parse_amount(value) == expected


def test_estimated_value_prefers_procedure_amount() -> None:
    raw = {
        "estimated-value-proc": "100",
        "estimated-value-cur-proc": "EUR",
        "estimated-value-lot": ["40", "50"],
        "estimated-value-cur-lot": ["EUR", "EUR"],
    }
    assert estimated_value(raw) == (Decimal("100.00"), "EUR")


def test_estimated_value_sums_lots_in_same_currency() -> None:
    raw = {"estimated-value-lot": ["40", "50.5"], "estimated-value-cur-lot": ["EUR", "EUR"]}
    assert estimated_value(raw) == (Decimal("90.50"), "EUR")


def test_estimated_value_ignores_lots_in_mixed_currencies() -> None:
    raw = {"estimated-value-lot": ["40", "50"], "estimated-value-cur-lot": ["EUR", "USD"]}
    assert estimated_value(raw) == (None, None)


def test_estimated_value_falls_back_to_lots_group() -> None:
    raw = {"estimated-value-glo": "70", "estimated-value-cur-glo": "EUR"}
    assert estimated_value(raw) == (Decimal("70.00"), "EUR")


def test_normalize_cpv_codes_deduplicates_and_validates() -> None:
    raw = {
        "classification-cpv": ["72500000", "72500000", "7250", "48000000-8"],
        "main-classification-proc": ["72500000"],
        "main-classification-lot": ["30213000"],
    }
    assert normalize_cpv_codes(raw) == ["72500000", "48000000", "30213000"]


def test_notice_url_prefers_italian_page_then_builds_one() -> None:
    raw = notice("707611-2026")
    assert notice_url(raw, "707611-2026").startswith("https://ted.europa.eu/it/")
    raw["links"]["html"].pop("ITA")
    assert notice_url(raw, "707611-2026").startswith("https://ted.europa.eu/en/")
    assert notice_url({}, "1-2026") == "https://ted.europa.eu/it/notice/-/detail/1-2026"


def test_change_reference_and_is_change_notice() -> None:
    change = notice("687833-2026")
    assert change_reference(change) == "68d34303-2d11-45ec-ae35-19a735ee975d"
    assert is_change_notice(change)
    original = notice("707611-2026")
    assert change_reference(original) is None
    assert not is_change_notice(original)


@pytest.mark.parametrize("links", [[], "x", {"html": "x"}, {"html": {"ITA": 3}}, None])
def test_notice_url_tolerates_malformed_links(links: Any) -> None:
    assert (
        notice_url({"links": links}, "1-2026") == "https://ted.europa.eu/it/notice/-/detail/1-2026"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("eur", "EUR"), (" EUR ", "EUR"), ("123", None), ("EURO", None), (None, None)],
)
def test_normalize_currency(value: Any, expected: str | None) -> None:
    assert normalize_currency(value) == expected


def test_invalid_currency_becomes_null_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    raw = notice("707611-2026")
    raw["estimated-value-cur-proc"] = "€€€"
    with caplog.at_level(logging.WARNING):
        tender = parse_notice(raw)
    assert tender.estimated_value == Decimal("293278.68")
    assert tender.currency is None
    assert "valuta" in caplog.text


def test_long_strings_do_not_break_validation() -> None:
    raw = notice("707611-2026")
    raw["notice-type"] = "x" * 2000
    raw["links"]["html"]["ITA"] = "https://ted.europa.eu/" + "a" * 2000
    raw["document-url-lot"] = ["https://example.invalid/" + "b" * 2000]
    raw["buyer-name"] = {"ita": ["c" * 2000]}
    tender = parse_notice(raw)
    assert len(tender.notice_type) == 100
    # l'URL italiano troppo lungo è scartato: si usa la pagina inglese
    assert tender.ted_url == "https://ted.europa.eu/en/notice/-/detail/707611-2026"
    assert tender.documents_url is not None and len(tender.documents_url) == 1000
    assert len(tender.buyer_name) == 500


def test_too_long_publication_number_raises_parse_error() -> None:
    raw = notice("707611-2026")
    raw["publication-number"] = "9" * 51
    with pytest.raises(NoticeParseError):
        parse_notice(raw)


def test_parse_notices_never_raises_on_unexpected_input(caplog: pytest.LogCaptureFixture) -> None:
    good = notice("707611-2026")
    with caplog.at_level(logging.WARNING):
        tenders = parse_notices([["non", "un", "avviso"], good, {"publication-number": 5}])  # type: ignore[list-item]
    assert [t.publication_number for t in tenders] == ["707611-2026"]
    assert "errore inatteso" in caplog.text


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://ted.europa.eu/x", True),
        ("HTTP://example.invalid", True),
        ("javascript:alert(1)", False),
        ("data:text/html,x", False),
        ("ftp://example.invalid", False),
        ("https://", False),
        (None, False),
    ],
)
def test_is_http_url(value: Any, expected: bool) -> None:
    assert is_http_url(value) is expected


def test_non_http_links_are_dropped() -> None:
    raw = notice("707611-2026")
    raw["document-url-lot"] = ["javascript:alert(1)", "https://example.invalid/doc.pdf"]
    raw["links"]["html"] = {"ITA": "data:text/html,x"}
    tender = parse_notice(raw)
    assert tender.documents_url == "https://example.invalid/doc.pdf"
    assert tender.ted_url == "https://ted.europa.eu/it/notice/-/detail/707611-2026"
