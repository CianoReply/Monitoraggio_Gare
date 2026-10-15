"""Test di TenderCreate (ADR-006)."""

import pytest
from pydantic import ValidationError

from backend.tests.domain.conftest import make_tender


def test_valid_tender_has_defaults() -> None:
    t = make_tender()
    assert t.description is None
    assert t.estimated_value is None
    assert t.raw_data == {}


def test_cpv_codes_are_deduplicated_keeping_order() -> None:
    t = make_tender(cpv_codes=["72000000", "48000000", "72000000"])
    assert t.cpv_codes == ["72000000", "48000000"]


@pytest.mark.parametrize("bad", ["7200", "7200000A", "720000000"])
def test_invalid_cpv_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        make_tender(cpv_codes=[bad])


def test_currency_is_uppercased_and_must_have_three_letters() -> None:
    assert make_tender(currency="eur").currency == "EUR"
    with pytest.raises(ValidationError):
        make_tender(currency="EURO")


def test_computed_fields_are_not_part_of_the_schema() -> None:
    fields = set(make_tender().model_dump())
    assert not fields & {"id", "relevance_score", "is_relevant", "discard_reason", "created_at"}


def test_negative_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_tender(estimated_value="-1")


def test_naive_deadline_is_rejected() -> None:
    from datetime import datetime

    with pytest.raises(ValidationError):
        make_tender(submission_deadline=datetime(2026, 11, 1, 12, 0))
