"""Test dei filtri automatici (T2.2) e della lettura di config.toml."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from backend.domain.config import (
    DEFAULT_CONFIG_PATH,
    ConfigError,
    FiltersConfig,
    load_filters_config,
    load_raw_config,
)
from backend.domain.filters import (
    FilterResult,
    apply_filters,
    filter_country,
    filter_cpv,
    filter_deadline,
    filter_min_value,
    filter_notice_type,
)
from backend.tests.domain.conftest import make_tender

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def config() -> FiltersConfig:
    return load_filters_config()


# --- Paese ---


@pytest.mark.parametrize("country", ["IT", "ita", " ITA ", None])
def test_country_kept(config: FiltersConfig, country: str | None) -> None:
    assert filter_country(country, config).kept


def test_country_discarded(config: FiltersConfig) -> None:
    result = filter_country("FR", config)
    assert not result.kept
    assert "FR" in (result.reason or "")


# --- CPV ---


@pytest.mark.parametrize(
    "cpv", [["72000000"], ["15000000", "48000000"], ["30213000"], ["64200000"]]
)
def test_cpv_kept(config: FiltersConfig, cpv: list[str]) -> None:
    assert filter_cpv(make_tender(cpv_codes=cpv), config).kept


@pytest.mark.parametrize("cpv", [["45000000"], ["30100000"], []])
def test_cpv_discarded(config: FiltersConfig, cpv: list[str]) -> None:
    result = filter_cpv(make_tender(cpv_codes=cpv), config)
    assert not result.kept
    assert result.reason


# --- Tipo di avviso ---


@pytest.mark.parametrize(
    "kind", ["bando di gara", "Avviso di preinformazione", "cn-standard", "pin-only"]
)
def test_notice_type_kept(config: FiltersConfig, kind: str) -> None:
    assert filter_notice_type(make_tender(notice_type=kind), config).kept


@pytest.mark.parametrize("kind", ["avviso di aggiudicazione", "can-standard", "altro"])
def test_notice_type_discarded(config: FiltersConfig, kind: str) -> None:
    result = filter_notice_type(make_tender(notice_type=kind), config)
    assert not result.kept
    assert kind in (result.reason or "")


def test_notice_type_correction_passes(config: FiltersConfig) -> None:
    tender = make_tender(notice_type="can-modif", parent_publication_number="000000-2026")
    assert filter_notice_type(tender, config).kept


# --- Scadenza ---


def test_deadline_future_or_missing_kept() -> None:
    future = make_tender(submission_deadline=datetime(2026, 11, 1, tzinfo=UTC))
    assert filter_deadline(future, NOW).kept
    assert filter_deadline(make_tender(submission_deadline=None), NOW).kept


def test_deadline_past_discarded() -> None:
    past = make_tender(submission_deadline=datetime(2026, 10, 1, tzinfo=UTC))
    assert not filter_deadline(past, NOW).kept
    assert not filter_deadline(make_tender(submission_deadline=NOW), NOW).kept


def test_deadline_defaults_to_current_time() -> None:
    assert not filter_deadline(
        make_tender(submission_deadline=datetime(2000, 1, 1, tzinfo=UTC))
    ).kept


# --- Importo minimo ---


def test_min_value_kept(config: FiltersConfig) -> None:
    assert filter_min_value(
        make_tender(estimated_value=Decimal("50000"), currency="EUR"), config
    ).kept
    assert filter_min_value(make_tender(estimated_value=None), config).kept
    # valuta diversa dall'euro: nessun confronto
    assert filter_min_value(make_tender(estimated_value=Decimal("10"), currency="USD"), config).kept


def test_min_value_discarded(config: FiltersConfig) -> None:
    result = filter_min_value(
        make_tender(estimated_value=Decimal("49999.99"), currency="EUR"), config
    )
    assert not result.kept
    assert "soglia" in (result.reason or "")


# --- Insieme dei filtri ---


def test_apply_filters_keeps_good_tender(config: FiltersConfig) -> None:
    tender = make_tender(estimated_value=Decimal("100000"), currency="EUR")
    assert apply_filters(tender, buyer_country="IT", config=config, now=NOW) == FilterResult.keep()


def test_apply_filters_returns_first_failing_rule(config: FiltersConfig) -> None:
    tender = make_tender(cpv_codes=["45000000"], estimated_value=Decimal("1"), currency="EUR")
    result = apply_filters(tender, buyer_country="FR", config=config, now=NOW)
    assert not result.kept
    assert "non italiano" in (result.reason or "")
    result = apply_filters(tender, buyer_country="IT", config=config, now=NOW)
    assert result.reason == "Nessun CPV nella categoria IT"


def test_apply_filters_loads_default_config() -> None:
    assert apply_filters(make_tender(), now=NOW).kept


# --- Configurazione ---


def _write(tmp_path: Path, min_value: str = "50000", cpv: str = '["72"]') -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
[filters]
min_value_eur = {min_value}
cpv_prefixes = {cpv}
allowed_countries = ["it"]
accepted_notice_type_terms = ["Bando"]
rejected_notice_type_terms = ["Aggiudicazione"]
""",
        encoding="utf-8",
    )
    return path


def test_changing_threshold_in_config_changes_result(tmp_path: Path) -> None:
    tender = make_tender(estimated_value=Decimal("80000"), currency="EUR")
    strict = load_filters_config(_write(tmp_path, min_value="100000"))
    lax = load_filters_config(_write(tmp_path, min_value="60000"))
    assert not filter_min_value(tender, strict).kept
    assert filter_min_value(tender, lax).kept


def test_changing_cpv_list_in_config_changes_result(tmp_path: Path) -> None:
    tender = make_tender(cpv_codes=["45000000"])
    assert not filter_cpv(tender, load_filters_config(_write(tmp_path))).kept
    assert filter_cpv(tender, load_filters_config(_write(tmp_path, cpv='["45"]'))).kept


def test_config_values_are_normalized(tmp_path: Path) -> None:
    cfg = load_filters_config(_write(tmp_path, min_value="1500.5"))
    assert cfg.min_value_eur == Decimal("1500.5")
    assert cfg.allowed_countries == ("IT",)
    assert cfg.accepted_notice_type_terms == ("bando",)
    assert cfg.rejected_notice_type_terms == ("aggiudicazione",)


def test_default_config_is_valid_and_readable() -> None:
    assert "filters" in load_raw_config(DEFAULT_CONFIG_PATH)
    cfg = load_filters_config()
    assert cfg.min_value_eur == Decimal(50000)
    assert cfg.cpv_prefixes == ("72", "48", "302", "324", "642")


@pytest.mark.parametrize(
    ("min_value", "cpv"),
    [("-1", '["72"]'), ('"molto"', '["72"]'), ("1", '["7"]'), ("1", '["ab"]'), ("1", "[]")],
)
def test_invalid_config_is_rejected(tmp_path: Path, min_value: str, cpv: str) -> None:
    with pytest.raises(ConfigError):
        load_filters_config(_write(tmp_path, min_value=min_value, cpv=cpv))


def test_missing_filters_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[other]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_filters_config(path)
