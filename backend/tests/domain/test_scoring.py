"""Test delle regole di punteggio (T2.3).

I casi "reali" vengono da `fixtures/ted_search_it_2026-10-14.json`: titolo (`title-proc`),
descrizione (`description-proc`), CPV, importo e scadenza (data `deadline-receipt-tender-date-lot`
+ ora `deadline-receipt-tender-time-lot`, con il fuso dato da TED) sono scritti a mano come farà
il parser, senza importarlo. Il voto atteso è calcolato a mano con i pesi predefiniti di
`config.toml`: se si ritarano i pesi, vanno aggiornati questi valori.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from backend.domain.config import ScoringConfig, load_scoring_config
from backend.domain.filters import FilterResult
from backend.domain.schemas import TenderCreate
from backend.domain.scoring import (
    compute_score,
    evaluate_tender,
    score_breakdown,
    total_to_score,
)
from backend.tests.domain.conftest import make_tender
from backend.tests.domain.scoring_helpers import ConfigFactory

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


def ted_deadline(date: str, time: str) -> datetime:
    """Scadenza come la compone il parser: data + ora con fuso (es. "12:00:00+02:00")."""
    return datetime.fromisoformat(f"{date}T{time}")


@pytest.fixture
def config() -> ScoringConfig:
    return load_scoring_config()


# (descrizione del caso, campi della gara, voto atteso)
REAL_NOTICES = [
    (
        "707611 gestione atti Codice della Strada: CPV core +2, scadenza 33 giorni +1 -> 3",
        {
            "title": "Affidamento del servizio di gestione degli atti provenienti dal Codice "
            "della Strada (C.d.S.), relativi al controllo elettronico della velocit&#224; "
            "di controdeduzione, supporto e assistenza legale",
            "description": "Affidamento del servizio di gestione degli atti provenienti dal "
            "Codice della Strada (C.d.S.), relativi al controllo elettronico della velocit&#224;",
            "cpv_codes": ["72500000"],
            "estimated_value": Decimal("293278.68"),
            "submission_deadline": ted_deadline("2026-11-16", "12:00:00+02:00"),
        },
        3,
    ),
    (
        # can-standard: è un esito, i filtri lo scartano; qui si verifica solo il voto (ADR-010).
        "707979 manutenzione suite AIRONE (ESITO, solo punteggio): core +2, importo 1,16 M +1 -> 3",
        {
            "title": "Affidamento del Servizio di manutenzione suite AIRONE 2000 e fornitura "
            "kiosk PRM",
            "description": "Affidamento del Servizio di manutenzione suite AIRONE 2000 e "
            "fornitura kiosk PRM",
            "cpv_codes": ["72253200"],
            "estimated_value": Decimal("1155807.90"),
        },
        3,
    ),
    (
        "708163 conservazione digitale: core +2, 1 keyword +0, importo +1, scadenza 40 giorni +1 "
        "-> 4",
        {
            "title": "Assistenza tecnica e manutenzione evolutiva sistema di conservazione "
            "digitale",
            "description": "Assistenza tecnica e manutenzione evolutiva sistema di conservazione "
            "digitale",
            "cpv_codes": ["72500000"],
            "estimated_value": Decimal("2664750"),
            "submission_deadline": ted_deadline("2026-11-23", "10:00:00+01:00"),
        },
        4,
    ),
    (
        "708865 hardware FlexPod: CPV IT +1, importo +1, scadenza 15 giorni +1 -> 3",
        {
            "title": "FORNITURA DELL'AMPLIAMENTO E AMMODERNAMENTO DELL'INFRASTRUTTURA FLEXPOD "
            "CISCO-NETAPP DELL'AMBIENTE DI PRODUZIONE CON RELATIVI SERVIZI DI SUPPORTO",
            "description": "Si rimanda ai documenti di gara",
            "cpv_codes": ["30210000"],
            "estimated_value": Decimal("1609833.34"),
            "submission_deadline": ted_deadline("2026-10-29", "12:00:00+01:00"),
        },
        3,
    ),
    (
        "709110 sistema dinamico licenze software: IT +1, 'software' (1 keyword) +0, 20 M +1 -> 2",
        {
            "title": "BANDO PER L'ISTITUZIONE DEL SISTEMA DINAMICO DI ACQUISIZIONE DELLE "
            "FORNITURE DI LICENZE SOFTWARE PER LIGURIA DIGITALE ED ENTI SOCI",
            "description": "BANDO PER L'ISTITUZIONE DEL SISTEMA DINAMICO DI ACQUISIZIONE DELLE "
            "FORNITURE DI LICENZE SOFTWARE PER LIGURIA DIGITALE ED ENTI SOCI",
            "cpv_codes": ["48517000"],
            "estimated_value": Decimal("20000000.00"),
        },
        2,
    ),
    (
        "709116 licenze software: IT +1, importo +1, scadenza 37 giorni +1 -> 3",
        {
            "title": "866-2026 FORNITURA LICENZE SOFTWARE",
            "description": "866-2026 FORNITURA LICENZE SOFTWARE",
            "cpv_codes": ["48218000"],
            "estimated_value": Decimal("2260500.48"),
            "submission_deadline": ted_deadline("2026-11-20", "12:00:00+01:00"),
        },
        3,
    ),
    (
        "710118 portale sismica: core +2, 'portale' nella descrizione (1 keyword) +0 -> 2",
        {
            "title": "Proc 4389/AP/2026",
            "description": "Proc 4389/AP/2026_PROCEDURA APERTA AI SENSI DELL'ART. 71 DEL D.LGS. "
            "36/2023 PER AFFIDAMENTO DEL SERVIZIO INFORMATICO PER LA GESTIONE E MANUTENZIONE "
            "DEL PORTALE REGIONALE S.I.SMI.CA. (SISTEMA INFORMATIVO DELLA SISMICA IN REGIONE "
            "CAMPANIA)",
            "cpv_codes": ["72510000"],
            "estimated_value": Decimal("853741.50"),
        },
        2,
    ),
    (
        "710485 tesserini venatori: core +2, importo +1, scadenza 30 giorni +1 -> 4",
        {
            "title": "Servizio per la realizzazione di Tesserini venatori e di portali "
            "faunistici della Regione Toscana - due Lotti",
            "description": "Servizio per la realizzazione di Tesserini venatori e di portali "
            "faunistici della Regione Toscana - due Lotti",
            "cpv_codes": ["72212000", "79824000"],
            "estimated_value": Decimal("1373972.76"),
            "submission_deadline": ted_deadline("2026-11-13", "13:00:00+01:00"),
        },
        4,
    ),
    (
        "711174 piattaforma welfare: IT +1 (72000000 non core), 'piattaforma' +0, importo +1 -> 2",
        {
            "title": "PROCEDURA APERTA, EX ART. 71 DEL D. LGS. 36/2023 E S.M.I., PER "
            "L'AFFIDAMENTO DELLA FORNITURA, DEL SERVIZIO DI GESTIONE E DI SUPPORTO DI UNA "
            "PIATTAFORMA WELFARE RIVOLTA AI DIPENDENTI DEL COMUNE DI MONZA",
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

ALL_CASES = REAL_NOTICES + SYNTHETIC


@pytest.mark.parametrize(
    ("fields", "expected"),
    [(f, e) for _, f, e in ALL_CASES],
    ids=[name.split(":")[0] for name, _, _ in ALL_CASES],
)
def test_expected_score(config: ScoringConfig, fields: dict[str, Any], expected: int) -> None:
    if fields.get("estimated_value") is not None:
        fields = {"currency": "EUR", **fields}
    assert compute_score(neutral(**fields), config, NOW) == expected


def test_at_least_ten_example_tenders_are_checked() -> None:
    assert len(ALL_CASES) >= 10


# --- Singoli criteri e confini ---


def test_core_cpv_beats_other_cpv_and_does_not_stack(config: ScoringConfig) -> None:
    tender = neutral(cpv_codes=["72000000", "72500000", "48000000"])
    comps = score_breakdown(tender, config, NOW).components
    assert [(c.rule, c.points) for c in comps] == [("cpv", 2)]


def test_deadline_boundaries(config: ScoringConfig) -> None:
    def points(days: float) -> int:
        tender = neutral(submission_deadline=NOW + timedelta(days=days))
        return score_breakdown(tender, config, NOW).total

    assert points(10) == 1 and points(60) == 1
    assert points(9.99) == 0 and points(60.01) == 0
    assert points(5) == 0 and points(4.99) == -1


def test_high_value_boundary_and_missing_currency(config: ScoringConfig) -> None:
    def total(value: str, currency: str | None) -> int:
        tender = neutral(estimated_value=Decimal(value), currency=currency)
        return score_breakdown(tender, config, NOW).total

    assert total("1000000", "EUR") == 1
    assert total("999999.99", "EUR") == 0
    assert total("1000000", None) == 1


def _keywords(config: ScoringConfig, title: str, description: str | None = None) -> list[str]:
    comps = score_breakdown(neutral(title=title, description=description), config, NOW).components
    return [word for c in comps if c.rule == "keywords" for word in c.detail.split(", ")]


def test_keywords_use_whole_words_title_description_and_html_entities(cfg: ConfigFactory) -> None:
    config = cfg(keyword_words_per_point="1", keyword_max_points="9")
    assert _keywords(config, "Servizi cloud", "con cybersecurity") == ["cloud", "cybersecurity"]
    assert _keywords(config, "Application programming") == []  # "app" non è in "application"
    assert _keywords(config, "Cloud cloud CLOUD") == ["cloud"]  # distinte, non occorrenze
    assert _keywords(config, "Portale per la città di Forl&#236; e cloud") == ["cloud", "portale"]


def test_default_keywords_need_two_distinct_words_for_one_point(config: ScoringConfig) -> None:
    assert _keywords(config, "Cloud cloud CLOUD") == []
    assert _keywords(config, "Sicurezza informatica e cloud") == ["cloud", "sicurezza informatica"]


def test_keyword_plurals_are_variants_of_the_same_word(cfg: ConfigFactory) -> None:
    config = cfg(keyword_words_per_point="1", keyword_max_points="9")
    assert _keywords(config, "Realizzazione di portali faunistici") == ["portale"]
    assert _keywords(config, "Il portale e i portali") == ["portale"]  # conta una volta
    assert _keywords(config, "Nuovi applicativi e piattaforme") == ["applicativo", "piattaforma"]
    assert _keywords(config, "Data center e datacenter") == ["datacenter"]


def test_default_config_recognizes_plurals(config: ScoringConfig) -> None:
    detail = _keywords(config, "Portali e applicativi per il cloud")
    assert detail == ["cloud", "applicativo", "portale"]


def test_overlapping_keywords_count_only_the_longest(cfg: ConfigFactory) -> None:
    config = cfg(keyword_words_per_point="1", keyword_max_points="9")
    # "software" è dentro "sviluppo software": vale solo "sviluppo software"
    assert _keywords(config, "Sviluppo software") == ["sviluppo software"]
    # ma se "software" compare anche da solo, conta come parola a sé
    assert _keywords(config, "Sviluppo software e licenze software") == [
        "sviluppo software",
        "software",
    ]
    assert _keywords(config, "Licenze software") == ["software"]


def test_overlap_does_not_inflate_the_score(config: ScoringConfig) -> None:
    only_overlap = neutral(title="Sviluppo software")
    assert score_breakdown(only_overlap, config, NOW).total == 0
    with_other = neutral(title="Sviluppo software in cloud")
    assert score_breakdown(with_other, config, NOW).total == 1


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
        compute_score(make_tender(), config, datetime(2026, 10, 14, 12, 0))


def test_default_now_is_current_time(config: ScoringConfig) -> None:
    far = neutral(submission_deadline=datetime.now(UTC) + timedelta(days=30))
    assert score_breakdown(far, config).total == 1
    assert compute_score(far, config) == 1


# --- Valutazione per upsert_tender (ADR-010) ---


def _good_tender() -> TenderCreate:
    return neutral(cpv_codes=["72500000"], estimated_value=Decimal("2000000"), currency="EUR")


def test_evaluate_kept_and_high_score_is_relevant(config: ScoringConfig) -> None:
    result = evaluate_tender(_good_tender(), FilterResult.keep(), config, NOW)
    assert (result.relevance_score, result.is_relevant, result.discard_reason) == (3, True, None)


def test_evaluate_kept_but_low_score_is_not_relevant(config: ScoringConfig) -> None:
    result = evaluate_tender(neutral(cpv_codes=["48000000"]), FilterResult.keep(), config, NOW)
    assert (result.relevance_score, result.is_relevant, result.discard_reason) == (1, False, None)


def test_evaluate_discarded_keeps_score_but_is_never_relevant(config: ScoringConfig) -> None:
    result = evaluate_tender(_good_tender(), FilterResult.discard("Scadenza passata"), config, NOW)
    assert result.relevance_score == 3  # il voto c'è anche per le scartate
    assert result.is_relevant is False
    assert result.discard_reason == "Scadenza passata"


def test_threshold_in_config_changes_relevance(cfg: ConfigFactory) -> None:
    assert evaluate_tender(
        _good_tender(), FilterResult.keep(), load_scoring_config(), NOW
    ).is_relevant
    strict = cfg(relevance_threshold="4")
    assert not evaluate_tender(_good_tender(), FilterResult.keep(), strict, NOW).is_relevant


def test_weights_and_keywords_in_config_change_score(cfg: ConfigFactory) -> None:
    tender = neutral(title="Gestione blockchain", cpv_codes=["72500000"])
    assert compute_score(tender, load_scoring_config(), NOW) == 2
    assert compute_score(tender, cfg(core_cpv_points="3"), NOW) == 3
    with_kw = cfg(keywords='["blockchain", "gestione"]')
    assert compute_score(tender, with_kw, NOW) == 3


def test_real_plural_notice_matches_keyword_with_one_word_per_point(cfg: ConfigFactory) -> None:
    """710485: "portali" nel titolo reale è riconosciuto come "portale"."""
    config = cfg(keyword_words_per_point="1")
    title = "Servizio per la realizzazione di Tesserini venatori e di portali faunistici"
    assert _keywords(config, title) == ["portale"]
