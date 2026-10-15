"""Test del punteggio di pertinenza (T2.3), del campione di validazione e della config [scoring].

I primi casi sono avvisi reali di `fixtures/ted_search_it_2026-10-14.json` (titolo, CPV, importo,
scadenza), costruiti a mano come `TenderCreate`. Il voto atteso è calcolato a mano con i pesi
predefiniti di `config.toml`; se si ritarano i pesi, vanno aggiornati questi valori.
"""

import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.domain.config import (
    ConfigError,
    ScoringConfig,
    load_scoring_config,
)
from backend.domain.filters import FilterResult
from backend.domain.schemas import TenderCreate
from backend.domain.scoring import (
    compute_score,
    evaluate_tender,
    score_breakdown,
    total_to_score,
)
from backend.domain.scoring_sample import main as sample_main
from backend.domain.scoring_sample import print_sample
from backend.domain.seed import seed
from backend.tests.domain.conftest import make_tender

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def neutral(**overrides: Any) -> TenderCreate:
    """Gara senza alcun criterio di punteggio attivo, salvo quelli passati in `overrides`."""
    base: dict[str, Any] = {
        "title": "Titolo neutro",
        "description": None,
        "cpv_codes": ["45000000"],
        "estimated_value": None,
        "currency": None,
        "submission_deadline": None,
    }
    return make_tender(**{**base, **overrides})


def d(date_str: str) -> datetime:
    """Mezzanotte del giorno indicato (le fixture TED danno solo la data)."""
    return datetime.fromisoformat(date_str).replace(tzinfo=UTC)


@pytest.fixture
def config() -> ScoringConfig:
    return load_scoring_config()


# (descrizione, campi della gara, voto atteso)
REAL_NOTICES = [
    (
        "707611 gestione atti Codice della Strada: CPV core +2, scadenza 32 giorni +1 -> 3",
        {
            "title": "Affidamento del servizio di gestione degli atti provenienti dal Codice "
            "della Strada, relativi al controllo elettronico della velocità",
            "cpv_codes": ["72500000"],
            "estimated_value": Decimal("293278.68"),
            "submission_deadline": d("2026-11-16"),
        },
        3,
    ),
    (
        "707979 manutenzione suite AIRONE: CPV core +2, importo 1,16 M +1 -> 3",
        {
            "title": "Affidamento del Servizio di manutenzione suite AIRONE 2000 e fornitura kiosk",
            "cpv_codes": ["72253200"],
            "estimated_value": Decimal("1155807.90"),
        },
        3,
    ),
    (
        "708163 conservazione digitale: core +2, importo +1, scadenza 40 giorni +1 -> 4",
        {
            "title": "Assistenza tecnica e manutenzione evolutiva sistema di conservazione "
            "digitale",
            "cpv_codes": ["72500000"],
            "estimated_value": Decimal("2664750"),
            "submission_deadline": d("2026-11-23"),
        },
        4,
    ),
    (
        "708865 hardware FlexPod: CPV IT +1, importo +1, scadenza 14 giorni +1 -> 3",
        {
            "title": "FORNITURA DELL'AMPLIAMENTO E AMMODERNAMENTO DELL'INFRASTRUTTURA FLEXPOD "
            "CISCO-NETAPP DELL'AMBIENTE DI PRODUZIONE",
            "cpv_codes": ["30210000"],
            "estimated_value": Decimal("1609833.34"),
            "submission_deadline": d("2026-10-29"),
        },
        3,
    ),
    (
        "709110 sistema dinamico licenze software: CPV IT +1, 1 keyword +0, importo 20 M +1 -> 2",
        {
            "title": "BANDO PER L'ISTITUZIONE DEL SISTEMA DINAMICO DI ACQUISIZIONE DELLE FORNITURE "
            "DI LICENZE SOFTWARE",
            "cpv_codes": ["48517000"],
            "estimated_value": Decimal("20000000.00"),
        },
        2,
    ),
    (
        "709116 licenze software: CPV IT +1, importo +1, scadenza 37 giorni +1 -> 3",
        {
            "title": "866-2026 FORNITURA LICENZE SOFTWARE",
            "cpv_codes": ["48218000"],
            "estimated_value": Decimal("2260500.48"),
            "submission_deadline": d("2026-11-20"),
        },
        3,
    ),
    (
        "710118 gestione informatica: CPV core +2, importo 854 k sotto soglia -> 2",
        {
            "title": "Proc 4389/AP/2026",
            "cpv_codes": ["72510000"],
            "estimated_value": Decimal("853741.50"),
        },
        2,
    ),
    (
        "710485 tesserini venatori: CPV core +2, importo +1, scadenza 29 giorni +1 -> 4",
        {
            "title": "Servizio per la realizzazione di Tesserini venatori e di portali faunistici "
            "della Regione Toscana - due Lotti",
            "cpv_codes": ["72212000", "79824000"],
            "estimated_value": Decimal("1373972.76"),
            "submission_deadline": d("2026-11-13"),
        },
        4,
    ),
    (
        "711174 piattaforma welfare: CPV IT +1 (72000000 non core), importo +1 -> 2",
        {
            "title": "PROCEDURA APERTA PER L'AFFIDAMENTO DELLA FORNITURA, DEL SERVIZIO DI GESTIONE "
            "E DI SUPPORTO DI UNA PIATTAFORMA WELFARE RIVOLTA AI DIPENDENTI",
            "cpv_codes": ["72000000", "72411000"],
            "estimated_value": Decimal("5229120"),
        },
        2,
    ),
]

SYNTHETIC = [
    (
        "due keyword = +1",
        {"title": "Servizi cloud e cybersecurity", "cpv_codes": ["72000000"]},
        2,
    ),
    (
        "quattro keyword = massimo +2; core +2, importo +1, scadenza 30 giorni +1 = 6 -> 5",
        {
            "title": "Cloud, cybersecurity, machine learning e big data",
            "cpv_codes": ["72200000"],
            "estimated_value": Decimal("2000000"),
            "submission_deadline": NOW + timedelta(days=30),
        },
        5,
    ),
    (
        "scadenza a 3 giorni = -1: core +2 -1 = 1",
        {
            "title": "Gara",
            "cpv_codes": ["72500000"],
            "submission_deadline": NOW + timedelta(days=3),
        },
        1,
    ),
    ("CPV non IT e nessun altro criterio: totale 0 -> 1", {"cpv_codes": ["45000000"]}, 1),
    (
        "scadenza già passata = penalità: IT +1 -1 = 0 -> 1",
        {"cpv_codes": ["72000000"], "submission_deadline": NOW - timedelta(days=2)},
        1,
    ),
    (
        "scadenza a 7 giorni: nessun effetto, CPV core +2 -> 2",
        {"cpv_codes": ["72500000"], "submission_deadline": NOW + timedelta(days=7)},
        2,
    ),
    (
        "importo in dollari: nessun +1; CPV IT +1 -> 1",
        {"cpv_codes": ["48000000"], "estimated_value": Decimal("5000000"), "currency": "USD"},
        1,
    ),
]


@pytest.mark.parametrize(
    ("fields", "expected"),
    [(f, e) for _, f, e in REAL_NOTICES + SYNTHETIC],
    ids=[name.split(":")[0] for name, _, _ in REAL_NOTICES + SYNTHETIC],
)
def test_expected_score(config: ScoringConfig, fields: dict, expected: int) -> None:
    if fields.get("estimated_value") is not None:
        fields = {"currency": "EUR", **fields}
    assert compute_score(neutral(**fields), config, NOW) == expected


def test_at_least_ten_example_tenders_are_checked() -> None:
    assert len(REAL_NOTICES) + len(SYNTHETIC) >= 10


# --- Singoli criteri e confini ---


def test_core_cpv_beats_other_cpv_and_does_not_stack(config: ScoringConfig) -> None:
    tender = neutral(cpv_codes=["72000000", "72500000", "48000000"])
    comps = score_breakdown(tender, config, NOW).components
    assert [(c.rule, c.points) for c in comps] == [("cpv", 2)]


def test_deadline_boundaries(config: ScoringConfig) -> None:
    def points(days: float) -> int:
        tender = neutral(cpv_codes=["45000000"], submission_deadline=NOW + timedelta(days=days))
        return score_breakdown(tender, config, NOW).total

    assert points(10) == 1 and points(60) == 1
    assert points(9.99) == 0 and points(60.01) == 0
    assert points(5) == 0 and points(4.99) == -1


def test_high_value_boundary_and_missing_currency(config: ScoringConfig) -> None:
    def total(value: str, currency: str | None) -> int:
        tender = neutral(cpv_codes=["45000000"], estimated_value=Decimal(value), currency=currency)
        return score_breakdown(tender, config, NOW).total

    assert total("1000000", "EUR") == 1
    assert total("999999.99", "EUR") == 0
    assert total("1000000", None) == 1


def test_keywords_use_whole_words_title_and_description_and_html_entities(
    config: ScoringConfig,
) -> None:
    def kw(title: str, description: str | None = None) -> list[str]:
        tender = neutral(cpv_codes=["45000000"], title=title, description=description)
        comps = score_breakdown(tender, config, NOW).components
        return [c.detail for c in comps if c.rule == "keywords"]

    assert kw("Servizi cloud", "con cybersecurity") == ["cloud, cybersecurity"]
    assert kw("Application programming") == []  # "app" non è dentro "application"
    assert kw("Cloud cloud CLOUD") == []  # una sola keyword distinta = 0 punti
    assert kw("Sicurezza informatica e cloud") == ["cloud, sicurezza informatica"]
    assert kw("Portale per la città di Forl&#236; e cloud") == ["cloud, portale"]


def test_total_to_score_clamps() -> None:
    assert [total_to_score(t) for t in (-3, 0, 1, 2, 3, 4, 5, 9)] == [1, 1, 1, 2, 3, 4, 5, 5]


def test_breakdown_explains_the_score(config: ScoringConfig) -> None:
    tender = neutral(
        title="Cloud e cybersecurity",
        cpv_codes=["72500000"],
        estimated_value=Decimal("1500000"),
        currency="EUR",
        submission_deadline=NOW + timedelta(days=20),
    )
    breakdown = score_breakdown(tender, config, NOW)
    assert [(c.rule, c.points) for c in breakdown.components] == [
        ("cpv", 2),
        ("keywords", 1),
        ("value", 1),
        ("deadline", 1),
    ]
    assert (breakdown.total, breakdown.score) == (5, 5)


def test_naive_now_is_rejected(config: ScoringConfig) -> None:
    with pytest.raises(ValueError, match="fuso orario"):
        compute_score(neutral(), config, datetime(2026, 10, 14, 12, 0))


def test_default_now_is_current_time(config: ScoringConfig) -> None:
    far = neutral(
        cpv_codes=["45000000"], submission_deadline=datetime.now(UTC) + timedelta(days=30)
    )
    assert compute_score(far, config) == 1
    assert score_breakdown(far, config).total == 1


# --- Valutazione per upsert_tender (ADR-010) ---


def test_evaluate_kept_and_high_score_is_relevant(config: ScoringConfig) -> None:
    tender = neutral(cpv_codes=["72500000"], estimated_value=Decimal("2000000"), currency="EUR")
    result = evaluate_tender(tender, FilterResult.keep(), config, NOW)
    assert (result.relevance_score, result.is_relevant, result.discard_reason) == (3, True, None)


def test_evaluate_kept_but_low_score_is_not_relevant(config: ScoringConfig) -> None:
    result = evaluate_tender(neutral(cpv_codes=["48000000"]), FilterResult.keep(), config, NOW)
    assert (result.relevance_score, result.is_relevant, result.discard_reason) == (1, False, None)


def test_evaluate_discarded_keeps_score_but_is_never_relevant(config: ScoringConfig) -> None:
    tender = neutral(cpv_codes=["72500000"], estimated_value=Decimal("2000000"), currency="EUR")
    result = evaluate_tender(tender, FilterResult.discard("Scadenza passata"), config, NOW)
    assert result.relevance_score == 3  # il voto c'è anche per le scartate
    assert result.is_relevant is False
    assert result.discard_reason == "Scadenza passata"


def test_threshold_in_config_changes_relevance(tmp_path: Path) -> None:
    tender = neutral(cpv_codes=["72500000"], estimated_value=Decimal("2000000"), currency="EUR")
    assert evaluate_tender(tender, FilterResult.keep(), load_scoring_config(), NOW).is_relevant
    strict = _write_config(tmp_path, relevance_threshold="4")
    assert not evaluate_tender(tender, FilterResult.keep(), strict, NOW).is_relevant


def test_weights_and_keywords_in_config_change_score(tmp_path: Path) -> None:
    tender = neutral(title="Gestione blockchain", cpv_codes=["72500000"])
    assert compute_score(tender, load_scoring_config(), NOW) == 2
    boosted = _write_config(tmp_path, core_cpv_points="3")
    assert compute_score(tender, boosted, NOW) == 3
    with_kw = _write_config(
        tmp_path, keywords='["blockchain", "gestione"]', keyword_words_per_point="2"
    )
    assert compute_score(tender, with_kw, NOW) == 3


# --- Configurazione [scoring] ---

BASE = {
    "relevance_threshold": "3",
    "core_cpv_prefixes": '["722", "725"]',
    "core_cpv_points": "2",
    "it_cpv_prefixes": '["72", "48"]',
    "other_cpv_points": "1",
    "keywords": '["cloud"]',
    "keyword_words_per_point": "2",
    "keyword_max_points": "2",
    "high_value_eur": "1000000",
    "high_value_points": "1",
    "deadline_ok_min_days": "10",
    "deadline_ok_max_days": "60",
    "deadline_ok_points": "1",
    "deadline_urgent_days": "5",
    "deadline_urgent_points": "-1",
}


def _write_path(tmp_path: Path, **overrides: str) -> Path:
    values = {**BASE, **overrides}
    body = "\n".join(f"{k} = {v}" for k, v in values.items())
    path = tmp_path / "config.toml"
    path.write_text(f"[scoring]\n{body}\n", encoding="utf-8")
    return path


def _write_config(tmp_path: Path, **overrides: str) -> ScoringConfig:
    return load_scoring_config(_write_path(tmp_path, **overrides))


def test_default_scoring_config_matches_the_plan() -> None:
    cfg = load_scoring_config()
    assert cfg.relevance_threshold == 3
    assert (cfg.core_cpv_points, cfg.other_cpv_points) == (2, 1)
    assert (cfg.keyword_words_per_point, cfg.keyword_max_points) == (2, 2)
    assert (cfg.high_value_eur, cfg.high_value_points) == (Decimal(1000000), 1)
    assert (cfg.deadline_ok_min_days, cfg.deadline_ok_max_days, cfg.deadline_ok_points) == (
        10,
        60,
        1,
    )
    assert (cfg.deadline_urgent_days, cfg.deadline_urgent_points) == (5, -1)
    assert "cloud" in cfg.keywords and "cybersecurity" in cfg.keywords


def test_valid_custom_config_is_loaded(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, keywords='["Cloud", " AI "]')
    assert cfg.keywords == ("cloud", "ai")


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
        {"keyword_words_per_point": "0"},
        {"keyword_max_points": "-1"},
        {"high_value_eur": "-5"},
        {"high_value_eur": "true"},
        {"high_value_points": "false"},
        {"deadline_ok_min_days": "70"},
        {"deadline_ok_min_days": "-1"},
        {"deadline_urgent_days": "-2"},
        {"deadline_urgent_points": '"meno uno"'},
    ],
)
def test_invalid_scoring_config_is_rejected_with_path(
    tmp_path: Path, override: dict[str, str]
) -> None:
    path = _write_path(tmp_path, **override)
    with pytest.raises(ConfigError) as excinfo:
        load_scoring_config(path)
    assert str(path) in str(excinfo.value)


@pytest.mark.parametrize("missing", list(BASE))
def test_missing_scoring_key_is_rejected(tmp_path: Path, missing: str) -> None:
    path = _write_path(tmp_path)
    lines = [
        ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith(missing)
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_scoring_config(path)


def test_missing_scoring_section_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[filters]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"\[scoring\]"):
        load_scoring_config(path)


# --- Seed e campione per la validazione ---


def test_seed_scores_come_from_scoring_rules(session: Session) -> None:
    seed(session, today=NOW.date())
    cfg = load_scoring_config()
    stream = io.StringIO()
    count = print_sample(
        session, cfg, limit=20, now=datetime(2026, 10, 14, 12, 0, tzinfo=UTC), out=stream
    )
    assert count == 20
    text = stream.getvalue()
    assert "ATTENZIONE" not in text  # voto salvato = voto ricalcolato
    assert "SCARTATA: CPV non pertinente" in text
    scores = [int(line[1]) for line in text.splitlines() if line.startswith("[")]
    assert scores == sorted(scores, reverse=True)
    assert set(scores) <= {1, 2, 3, 4, 5}


def test_print_sample_respects_limit(session: Session) -> None:
    seed(session, today=NOW.date())
    stream = io.StringIO()
    assert print_sample(session, load_scoring_config(), limit=3, now=NOW, out=stream) == 3
    assert sum(1 for line in stream.getvalue().splitlines() if line.startswith("[")) == 3


def test_print_sample_flags_score_mismatch(session: Session) -> None:
    seed(session, today=NOW.date())
    from sqlalchemy import select

    from backend.domain.models import Tender

    tender = session.scalars(select(Tender).order_by(Tender.id)).first()
    tender.relevance_score = 5 if tender.relevance_score != 5 else 1
    stream = io.StringIO()
    print_sample(session, load_scoring_config(), limit=20, now=NOW, out=stream)
    assert "ATTENZIONE: ricalcolato" in stream.getvalue()


def test_sample_main_reads_database_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sqlalchemy import create_engine

    from backend.domain.models import Base

    url = f"sqlite:///{tmp_path / 'sample.db'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed(session)
        session.commit()
    monkeypatch.setenv("DATABASE_URL", url)
    sample_main(["--limit", "5"])
    out = capsys.readouterr().out
    assert "5 gare stampate." in out
    assert "criteri:" in out
