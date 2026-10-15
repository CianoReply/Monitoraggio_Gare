"""Test della sezione [scoring] di config.toml, del seed valutato e del campione di validazione."""

import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.domain.config import ConfigError, load_scoring_config
from backend.domain.filters import FilterResult
from backend.domain.models import Base, Tender
from backend.domain.scoring import evaluate_tender
from backend.domain.scoring_sample import _to_create, print_sample, select_sample
from backend.domain.scoring_sample import main as sample_main
from backend.domain.seed import seed
from backend.tests.domain.scoring_helpers import (
    BASE_SCORING,
    ConfigFactory,
    write_scoring_path,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_default_scoring_config_matches_the_plan() -> None:
    config = load_scoring_config()
    assert config.relevance_threshold == 3
    assert (config.core_cpv_points, config.other_cpv_points) == (2, 1)
    assert (config.keyword_words_per_point, config.keyword_max_points) == (2, 2)
    assert (config.high_value_eur, config.high_value_points) == (Decimal(1000000), 1)
    assert config.deadline_ok_min_days == 10
    assert config.deadline_ok_max_days == 60
    assert config.deadline_ok_points == 1
    assert (config.deadline_urgent_days, config.deadline_urgent_points) == (5, -1)
    assert "cloud" in config.keywords and "portale|portali" in config.keywords
    # "ai" e "data" da soli non sono keyword (preposizione e parola "data")
    assert "ai" not in config.keywords and "data" not in config.keywords


def test_valid_custom_config_is_loaded(cfg: ConfigFactory) -> None:
    config = cfg(keywords='["Cloud", " AI ", "Portale|Portali"]')
    assert config.keywords == ("cloud", "ai", "portale|portali")


@pytest.mark.parametrize(
    "override",
    [
        {"relevance_threshold": "0"},
        {"relevance_threshold": "6"},
        {"relevance_threshold": "true"},
        {"relevance_threshold": "2.5"},
        {"core_cpv_prefixes": "[]"},
        {"core_cpv_prefixes": '["7"]'},
        {"it_cpv_prefixes": '"72"'},
        {"core_cpv_points": '"due"'},
        {"other_cpv_points": "1.5"},
        {"keywords": "[]"},
        {"keywords": '["cloud", 3]'},
        {"keywords": '["cloud", "|"]'},
        {"keyword_words_per_point": "0"},
        {"keyword_max_points": "-1"},
        {"high_value_eur": "-5"},
        {"high_value_eur": "true"},
        {"high_value_eur": '"molto"'},
        {"high_value_points": "false"},
        {"deadline_ok_min_days": "70"},
        {"deadline_ok_min_days": "-1"},
        {"deadline_urgent_days": "-2"},
        {"deadline_urgent_days": "10"},  # uguale a deadline_ok_min_days
        {"deadline_urgent_days": "12"},
        {"deadline_urgent_points": '"meno uno"'},
    ],
)
def test_invalid_scoring_config_is_rejected_with_path(
    tmp_path: Path, override: dict[str, str]
) -> None:
    path = write_scoring_path(tmp_path, **override)
    with pytest.raises(ConfigError) as excinfo:
        load_scoring_config(path)
    assert str(path) in str(excinfo.value)


def test_urgent_days_below_ok_min_days_is_accepted(cfg: ConfigFactory) -> None:
    assert cfg(deadline_urgent_days="9").deadline_urgent_days == 9


@pytest.mark.parametrize("missing", list(BASE_SCORING))
def test_missing_scoring_key_is_rejected(tmp_path: Path, missing: str) -> None:
    path = write_scoring_path(tmp_path)
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(missing + " ")
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_scoring_config(path)


def test_missing_scoring_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[filters]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"\[scoring\]"):
        load_scoring_config(path)


# --- Seed valutato con le regole ---


def test_seed_scores_match_evaluate_tender(session: Session) -> None:
    """Il voto salvato dal seed coincide con quello ricalcolato da `evaluate_tender`."""
    seed(session, today=NOW.date())
    config = load_scoring_config()
    for tender in session.scalars(select(Tender)):
        result = (
            FilterResult.keep()
            if tender.discard_reason is None
            else FilterResult.discard(tender.discard_reason)
        )
        expected = evaluate_tender(_to_create(tender), result, config, NOW)
        assert tender.relevance_score == expected.relevance_score
        assert tender.is_relevant == expected.is_relevant


def test_seed_known_scores_are_hand_checked(session: Session) -> None:
    seed(session, today=NOW.date())
    by_number = {t.publication_number: t for t in session.scalars(select(Tender))}
    # INPS data center: core +2, cloud + data center +1, importo 9,5 M +1, scadenza 42 giorni +1
    cloud = by_number["900006-2026"]
    assert (cloud.relevance_score, cloud.is_relevant) == (5, True)
    # Lavori edili scartati: nessun CPV IT, importo 1,8 M +1, scadenza 16 giorni +1 = 2 (ADR-010)
    works = by_number["900016-2026"]
    assert works.relevance_score == 2
    assert works.is_relevant is False
    assert works.discard_reason == "CPV non pertinente (non IT)"
    # Pescara: importo 45.000 sotto la soglia di 50.000 dei filtri
    assert by_number["900019-2026"].discard_reason == "Importo sotto la soglia minima"
    assert all(1 <= t.relevance_score <= 5 for t in by_number.values())


# --- Campione per la validazione ---


def test_print_sample_orders_by_score_and_reports_discarded(session: Session) -> None:
    seed(session, today=NOW.date())
    stream = io.StringIO()
    count = print_sample(session, load_scoring_config(), limit=20, now=NOW, out=stream)
    text = stream.getvalue()
    assert count == 20
    assert "ATTENZIONE" not in text  # voto salvato = voto ricalcolato
    assert "SCARTATA: CPV non pertinente" in text
    scores = [int(line[1]) for line in text.splitlines() if line.startswith("[")]
    assert scores == sorted(scores, reverse=True)


def test_print_sample_respects_limit(session: Session) -> None:
    seed(session, today=NOW.date())
    stream = io.StringIO()
    assert print_sample(session, load_scoring_config(), limit=3, now=NOW, out=stream) == 3
    assert sum(1 for line in stream.getvalue().splitlines() if line.startswith("[")) == 3


def test_stratified_sample_shows_every_score(session: Session) -> None:
    seed(session, today=NOW.date())
    sample = select_sample(session, per_score=2)
    scores = [t.relevance_score for t in sample]
    assert scores == sorted(scores, reverse=True)
    present = {t.relevance_score for t in session.scalars(select(Tender))}
    assert set(scores) == present
    assert all(scores.count(s) <= 2 for s in present)
    assert min(scores) < 3  # compaiono anche i voti bassi


def test_sample_orders_missing_deadlines_last_within_a_score(session: Session) -> None:
    seed(session, today=NOW.date())
    for score in {t.relevance_score for t in session.scalars(select(Tender))}:
        group = [t for t in select_sample(session, limit=100) if t.relevance_score == score]
        deadlines = [t.submission_deadline for t in group]
        none_positions = [i for i, d in enumerate(deadlines) if d is None]
        assert none_positions == list(range(len(deadlines) - len(none_positions), len(deadlines)))


def test_print_sample_flags_score_mismatch(session: Session) -> None:
    seed(session, today=NOW.date())
    tender = session.scalars(select(Tender).order_by(Tender.id)).first()
    assert tender is not None
    tender.relevance_score = 5 if tender.relevance_score != 5 else 1
    stream = io.StringIO()
    print_sample(session, load_scoring_config(), limit=20, now=NOW, out=stream)
    assert "ATTENZIONE: ricalcolato" in stream.getvalue()


def test_sample_main_reads_database_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'sample.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed(db)
        db.commit()
    monkeypatch.setenv("DATABASE_URL", url)
    sample_main(["--limit", "5"])
    out = capsys.readouterr().out
    assert "5 gare stampate." in out
    assert "criteri:" in out
    sample_main(["--per-score", "1"])
    assert "gare stampate." in capsys.readouterr().out


def test_sample_main_rejects_invalid_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    with pytest.raises(SystemExit):
        sample_main(["--limit", "0"])
    with pytest.raises(SystemExit):
        sample_main(["--per-score", "0"])
