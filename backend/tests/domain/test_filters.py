"""Test dei filtri automatici (T2.2) e della lettura di config.toml."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

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
ROME = ZoneInfo("Europe/Rome")


@pytest.fixture
def config() -> FiltersConfig:
    return load_filters_config()


# --- FilterResult ---


def test_filter_result_constructors() -> None:
    assert FilterResult.keep() == FilterResult(True, None)
    discarded = FilterResult.discard("motivo")
    assert (discarded.kept, discarded.reason) == (False, "motivo")


# --- Paese ---


@pytest.mark.parametrize("country", ["ITA", "ita", " ITA ", ["ITA"], ["FRA", "ITA"], None])
def test_country_kept(config: FiltersConfig, country: str | list[str] | None) -> None:
    assert filter_country(country, config).kept


@pytest.mark.parametrize("country", ["FRA", "IT", ["FRA", "DEU"], []])
def test_country_discarded(config: FiltersConfig, country: str | list[str]) -> None:
    result = filter_country(country, config)
    assert not result.kept
    assert "non italiano" in (result.reason or "")


# --- CPV ---


@pytest.mark.parametrize(
    "cpv", [["72000000"], ["15000000", "48000000"], ["30213000"], ["64200000"], ["32400000"]]
)
def test_cpv_kept(config: FiltersConfig, cpv: list[str]) -> None:
    assert filter_cpv(make_tender(cpv_codes=cpv), config).kept


@pytest.mark.parametrize("cpv", [["45000000"], ["30100000"], []])
def test_cpv_discarded(config: FiltersConfig, cpv: list[str]) -> None:
    result = filter_cpv(make_tender(cpv_codes=cpv), config)
    assert not result.kept
    assert result.reason


# --- Tipo di avviso ---


@pytest.mark.parametrize("kind", ["cn-standard", "CN-Social", " cn-desg "])
def test_notice_type_kept(config: FiltersConfig, kind: str) -> None:
    assert filter_notice_type(make_tender(notice_type=kind), config).kept


@pytest.mark.parametrize(
    ("kind", "detail"),
    [
        ("can-standard", "esito, non bando"),
        ("can-modif", "esito, non bando"),
        ("veat", "esito, non bando"),
        ("pin-only", "preinformazione, non bando"),
        ("pmc", "non è un bando"),
        ("cn-standardx", "non è un bando"),  # confronto esatto, non per sottostringa
    ],
)
def test_notice_type_discarded(config: FiltersConfig, kind: str, detail: str) -> None:
    result = filter_notice_type(make_tender(notice_type=kind), config)
    assert not result.kept
    assert result.reason == f"Tipo di avviso {kind}: {detail}"


def test_notice_type_correction_is_kept_even_if_not_a_notice_we_accept(
    config: FiltersConfig,
) -> None:
    correction = make_tender(notice_type="can-modif", parent_publication_number="abc-01")
    assert filter_notice_type(correction, config).kept
    same_type = make_tender(notice_type="cn-standard", parent_publication_number="abc-01")
    assert filter_notice_type(same_type, config).kept


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
    old = make_tender(submission_deadline=datetime(2000, 1, 1, tzinfo=UTC))
    assert not filter_deadline(old).kept
    assert filter_deadline(make_tender(submission_deadline=datetime(2999, 1, 1, tzinfo=UTC))).kept


def test_deadline_compares_instants_across_time_zones() -> None:
    # 13:00+02:00 = 11:00 UTC: passata rispetto a 12:00 UTC anche se "13" > "12" in locale.
    local_past = make_tender(
        submission_deadline=datetime(2026, 10, 15, 13, 0, tzinfo=timezone(timedelta(hours=2)))
    )
    assert not filter_deadline(local_past, NOW).kept
    # 11:00-02:00 = 13:00 UTC: futura anche se "11" < "12" in locale.
    local_future = make_tender(
        submission_deadline=datetime(2026, 10, 15, 11, 0, tzinfo=timezone(timedelta(hours=-2)))
    )
    assert filter_deadline(local_future, NOW).kept


def test_deadline_with_now_in_rome_time_zone() -> None:
    now_rome = datetime(2026, 10, 15, 14, 0, tzinfo=ROME)  # 12:00 UTC (ora legale)
    assert now_rome.astimezone(UTC) == NOW
    just_before = make_tender(submission_deadline=datetime(2026, 10, 15, 11, 59, tzinfo=UTC))
    just_after = make_tender(submission_deadline=datetime(2026, 10, 15, 12, 1, tzinfo=UTC))
    assert not filter_deadline(just_before, now_rome).kept
    assert filter_deadline(just_after, now_rome).kept


def test_deadline_rejects_naive_now() -> None:
    with pytest.raises(ValueError, match="fuso orario"):
        filter_deadline(make_tender(), datetime(2026, 10, 15, 12, 0))


# --- Importo minimo ---


def test_min_value_kept(config: FiltersConfig) -> None:
    exact = make_tender(estimated_value=Decimal("50000"), currency="EUR")
    assert filter_min_value(exact, config).kept
    assert filter_min_value(make_tender(estimated_value=None), config).kept
    # valuta diversa dall'euro: nessun confronto
    assert filter_min_value(make_tender(estimated_value=Decimal("10"), currency="USD"), config).kept


def test_min_value_discarded(config: FiltersConfig) -> None:
    low = make_tender(estimated_value=Decimal("49999.99"), currency="EUR")
    result = filter_min_value(low, config)
    assert not result.kept
    assert "soglia" in (result.reason or "")


def test_min_value_without_currency_is_treated_as_euro(config: FiltersConfig) -> None:
    assert not filter_min_value(
        make_tender(estimated_value=Decimal("100"), currency=None), config
    ).kept
    assert filter_min_value(
        make_tender(estimated_value=Decimal("90000"), currency=None), config
    ).kept


# --- Insieme dei filtri ---


def test_apply_filters_keeps_good_tender(config: FiltersConfig) -> None:
    tender = make_tender(
        notice_type="cn-standard", estimated_value=Decimal("100000"), currency="EUR"
    )
    result = apply_filters(tender, buyer_country=["ITA"], config=config, now=NOW)
    assert result == FilterResult.keep()


def test_apply_filters_returns_first_failing_rule(config: FiltersConfig) -> None:
    tender = make_tender(
        notice_type="cn-standard", cpv_codes=["45000000"], estimated_value=Decimal("1")
    )
    result = apply_filters(tender, buyer_country=["FRA"], config=config, now=NOW)
    assert "non italiano" in (result.reason or "")
    result = apply_filters(tender, buyer_country=["ITA"], config=config, now=NOW)
    assert result.reason == "Nessun CPV nella categoria IT"


def test_apply_filters_requires_buyer_country(config: FiltersConfig) -> None:
    tender = make_tender(notice_type="cn-standard")
    with pytest.raises(TypeError):
        apply_filters(tender, config=config, now=NOW)  # type: ignore[call-arg]
    assert apply_filters(tender, buyer_country=None, config=config, now=NOW).kept


# --- Configurazione ---


def _write(tmp_path: Path, **overrides: str) -> Path:
    values = {
        "min_value_eur": "50000",
        "cpv_prefixes": '["72"]',
        "allowed_countries": '["ita"]',
        "accepted_notice_types": '["CN-Standard"]',
    }
    values.update(overrides)
    body = "\n".join(f"{k} = {v}" for k, v in values.items())
    path = tmp_path / "config.toml"
    path.write_text(f"[filters]\n{body}\n", encoding="utf-8")
    return path


def test_changing_threshold_in_config_changes_result(tmp_path: Path) -> None:
    tender = make_tender(estimated_value=Decimal("80000"), currency="EUR")
    strict = load_filters_config(_write(tmp_path, min_value_eur="100000"))
    lax = load_filters_config(_write(tmp_path, min_value_eur="60000"))
    assert not filter_min_value(tender, strict).kept
    assert filter_min_value(tender, lax).kept


def test_changing_cpv_list_in_config_changes_result(tmp_path: Path) -> None:
    tender = make_tender(cpv_codes=["45000000"])
    assert not filter_cpv(tender, load_filters_config(_write(tmp_path))).kept
    assert filter_cpv(tender, load_filters_config(_write(tmp_path, cpv_prefixes='["45"]'))).kept


def test_changing_notice_types_in_config_changes_result(tmp_path: Path) -> None:
    tender = make_tender(notice_type="pin-only")
    assert not filter_notice_type(tender, load_filters_config(_write(tmp_path))).kept
    cfg = load_filters_config(_write(tmp_path, accepted_notice_types='["pin-only"]'))
    assert filter_notice_type(tender, cfg).kept


def test_config_values_are_normalized(tmp_path: Path) -> None:
    cfg = load_filters_config(_write(tmp_path, min_value_eur="1500.5"))
    assert cfg.min_value_eur == Decimal("1500.5")
    assert cfg.allowed_countries == ("ITA",)
    assert cfg.accepted_notice_types == ("cn-standard",)


def test_default_config_is_valid_and_readable() -> None:
    assert "filters" in load_raw_config(DEFAULT_CONFIG_PATH)
    assert "filters" in load_raw_config()
    cfg = load_filters_config()
    assert cfg.min_value_eur == Decimal(50000)
    assert cfg.cpv_prefixes == ("72", "48", "302", "324", "642")
    assert cfg.allowed_countries == ("ITA",)
    assert cfg.accepted_notice_types == ("cn-standard", "cn-social", "cn-desg")


def test_load_raw_config_reads_given_file(tmp_path: Path) -> None:
    path = tmp_path / "x.toml"
    path.write_text("[a]\nb = 1\n", encoding="utf-8")
    assert load_raw_config(path) == {"a": {"b": 1}}


@pytest.mark.parametrize(
    "override",
    [
        {"min_value_eur": "-1"},
        {"min_value_eur": '"molto"'},
        {"min_value_eur": "true"},
        {"cpv_prefixes": '["7"]'},
        {"cpv_prefixes": '["ab"]'},
        {"cpv_prefixes": "[]"},
        {"cpv_prefixes": '"72"'},
        {"cpv_prefixes": "[72]"},
        {"allowed_countries": "[]"},
        {"allowed_countries": '"ITA"'},
        {"allowed_countries": "[1, 2]"},
        {"allowed_countries": '[""]'},
        {"allowed_countries": '["ITA", 3]'},
        {"accepted_notice_types": "[]"},
        {"accepted_notice_types": '"cn-standard"'},
        {"accepted_notice_types": "[true]"},
        {"accepted_notice_types": '["  "]'},
    ],
)
def test_invalid_config_value_is_rejected_with_path(
    tmp_path: Path, override: dict[str, str]
) -> None:
    path = _write(tmp_path, **override)
    with pytest.raises(ConfigError) as excinfo:
        load_filters_config(path)
    assert str(path) in str(excinfo.value)


@pytest.mark.parametrize(
    "missing", ["min_value_eur", "cpv_prefixes", "allowed_countries", "accepted_notice_types"]
)
def test_missing_key_is_rejected(tmp_path: Path, missing: str) -> None:
    path = _write(tmp_path)
    lines = [
        ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith(missing)
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ConfigError, match=missing):
        load_filters_config(path)


def test_missing_filters_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[other]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"\[filters\]"):
        load_filters_config(path)


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "non_esiste.toml"
    with pytest.raises(ConfigError) as excinfo:
        load_filters_config(path)
    assert str(path) in str(excinfo.value)


def test_malformed_toml_is_a_config_error(tmp_path: Path) -> None:
    path = tmp_path / "rotto.toml"
    path.write_text("[filters\nmin_value_eur = ", encoding="utf-8")
    with pytest.raises(ConfigError) as excinfo:
        load_filters_config(path)
    assert str(path) in str(excinfo.value)
