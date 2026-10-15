"""Test su un vero PostgreSQL (marker `postgres`), saltati senza `TEST_POSTGRES_URL`.

Servono per ciò che SQLite non verifica: vincoli CHECK, tipi con fuso, ordinamento dei null, limiti
numerici e ricerche di testo. Il database deve avere un nome che termina con `_test`, perché i test
CREANO e CANCELLANO le tabelle. Esempio:

    createdb radar_test
    TEST_POSTGRES_URL=postgresql+psycopg://radar:radar_dev@localhost/radar_test pytest -m postgres

DA VERIFICARE: questi test non sono stati eseguiti nell'ambiente di sviluppo (nessun PostgreSQL).
"""

import os
import warnings
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from backend.domain.models import Base, Report, ReportStatus
from backend.domain.repository import list_tenders, upsert_tender
from backend.domain.schemas import TenderEvaluation
from backend.tests.domain.conftest import make_tender

with warnings.catch_warnings():  # il marker non è registrato in pyproject.toml (file condiviso)
    warnings.simplefilter("ignore")
    postgres = pytest.mark.postgres

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL", "").strip()
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "domain" / "alembic.ini"
TABLES = {"tenders", "documents", "reports", "report_fields", "ingestion_runs"}

pytestmark = [
    postgres,
    pytest.mark.skipif(
        not POSTGRES_URL, reason="serve un database PostgreSQL di prova: imposta TEST_POSTGRES_URL"
    ),
]


def _reset(engine: Engine) -> None:
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def require_test_database(url: str) -> None:
    """Rifiuta di lavorare su un database il cui nome non termina con `_test`."""
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.fail(
            f"Il database di prova deve avere un nome che termina con _test "
            f"(trovato {database!r}): i test cancellano le tabelle."
        )


@pytest.fixture
def pg_engine() -> Iterator[Engine]:
    require_test_database(POSTGRES_URL)
    engine = create_engine(POSTGRES_URL)
    _reset(engine)
    yield engine
    _reset(engine)
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine: Engine) -> Iterator[Session]:
    Base.metadata.create_all(pg_engine)
    with Session(pg_engine) as session:
        yield session


def _add(session: Session, number: str, score: int = 3, **kw: object):  # noqa: ANN202
    tender, _ = upsert_tender(
        session,
        make_tender(publication_number=number, **kw),  # type: ignore[arg-type]
        TenderEvaluation(score, score >= 3),
    )
    return tender


# --- Migrazioni ---


def test_alembic_upgrade_and_downgrade(pg_engine: Engine) -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", POSTGRES_URL)
    command.upgrade(cfg, "head")
    assert TABLES <= set(inspect(pg_engine).get_table_names())
    with pg_engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
    command.downgrade(cfg, "base")
    assert not TABLES & set(inspect(pg_engine).get_table_names())


# --- Vincoli ---


def test_enum_check_constraint_rejects_unknown_values(pg_session: Session) -> None:
    tender = _add(pg_session, "a")
    pg_session.commit()
    with pytest.raises(IntegrityError):
        pg_session.execute(
            text("INSERT INTO documents (tender_id, name, status) VALUES (:t, 'x', 'inventato')"),
            {"t": tender.id},
        )
    pg_session.rollback()


def test_unique_report_per_tender(pg_session: Session) -> None:
    tender = _add(pg_session, "a")
    pg_session.add(Report(tender_id=tender.id, summary="s", ai_label="x"))
    pg_session.commit()
    pg_session.add(Report(tender_id=tender.id, summary="s2", ai_label="x"))
    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()


def test_numeric_and_integer_limits_match_the_domain_limits(pg_session: Session) -> None:
    _add(pg_session, "ok", estimated_value=Decimal("9999999999999999.99"), currency="EUR")
    pg_session.commit()
    # 10^16 non sta in Numeric(18, 2): per questo il dominio lo rifiuta.
    with pytest.raises(DBAPIError):
        pg_session.execute(
            text(
                "INSERT INTO tenders (publication_number, title, buyer_name, notice_type, "
                "publication_date, ted_url, relevance_score, is_relevant, estimated_value, "
                "cpv_codes, raw_data, created_at, updated_at) "
                "VALUES ('big', 't', 'b', 'cn-standard', "
                "'2026-10-01', 'u', 3, true, 10000000000000000, '[]', '{}', now(), now())"
            )
        )
    pg_session.rollback()


def test_nul_character_is_rejected_by_the_database_hence_by_the_domain(pg_session: Session) -> None:
    with pytest.raises(DBAPIError):
        pg_session.execute(text("SELECT :value"), {"value": "a" + chr(0) + "b"})
    pg_session.rollback()


# --- Fusi orari ---


def test_timezones_round_trip_as_aware_utc(pg_engine: Engine, pg_session: Session) -> None:
    deadline = datetime(2026, 11, 20, 12, 0, tzinfo=timezone(timedelta(hours=1)))
    tender = _add(pg_session, "a", submission_deadline=deadline)
    pg_session.commit()
    tender_id = tender.id
    with Session(pg_engine) as reader:
        loaded = reader.get(type(tender), tender_id)
        assert loaded is not None
        assert loaded.submission_deadline == deadline
        assert loaded.submission_deadline.utcoffset() == timedelta(0)
        assert loaded.created_at.tzinfo is not None
        assert loaded.created_at.astimezone(UTC) - datetime.now(UTC) < timedelta(minutes=5)


def test_deadline_range_covers_the_whole_rome_day(pg_session: Session) -> None:
    rome_winter = timezone(timedelta(hours=1))
    _add(pg_session, "late", submission_deadline=datetime(2026, 11, 20, 23, 30, tzinfo=rome_winter))
    _add(pg_session, "next", submission_deadline=datetime(2026, 11, 21, 0, 30, tzinfo=rome_winter))
    day = date(2026, 11, 20)
    page = list_tenders(pg_session, deadline_from=day, deadline_to=day)
    assert [r.tender.publication_number for r in page.items] == ["late"]


# --- Ordinamento e filtri ---


def test_default_order_puts_missing_deadlines_last(pg_session: Session) -> None:
    def d(day: int) -> datetime:
        return datetime(2026, 11, day, tzinfo=UTC)

    _add(pg_session, "a", 3, submission_deadline=d(5))
    _add(pg_session, "b", 5, submission_deadline=None)
    _add(pg_session, "c", 5, submission_deadline=d(10))
    _add(pg_session, "d", 3, submission_deadline=None)
    order = [r.tender.publication_number for r in list_tenders(pg_session).items]
    assert order == ["c", "b", "a", "d"]
    by_deadline_page = list_tenders(pg_session, sort="deadline")
    by_deadline = [r.tender.publication_number for r in by_deadline_page.items]
    assert by_deadline == ["a", "c", "b", "d"]


def test_text_search_is_case_insensitive_and_escapes_wildcards(pg_session: Session) -> None:
    _add(pg_session, "a", title="Piattaforma CLOUD per la città", description=None)
    _add(pg_session, "b", title="Altro", description="migrazione al cloud")
    _add(pg_session, "c", title="100% pronto")
    _add(pg_session, "d", title="sotto_linea")
    assert list_tenders(pg_session, q="cloud").total == 2
    assert [r.tender.publication_number for r in list_tenders(pg_session, q="100%").items] == ["c"]
    assert [r.tender.publication_number for r in list_tenders(pg_session, q="_").items] == ["d"]
    assert list_tenders(pg_session, q="%").total == 1


def test_report_status_filter_and_derived_status(pg_session: Session) -> None:
    a = _add(pg_session, "a", 5)
    b = _add(pg_session, "b", 4)
    _add(pg_session, "c", 3)
    pg_session.add_all(
        [
            Report(tender=a, summary="s", status=ReportStatus.TO_REVIEW, ai_label="x"),
            Report(tender=b, summary="s", status=ReportStatus.VERIFIED, ai_label="x"),
        ]
    )
    pg_session.flush()
    rows = list_tenders(pg_session).items
    assert [(r.tender.publication_number, r.report_status) for r in rows] == [
        ("a", "to_review"),
        ("b", "verified"),
        ("c", "none"),
    ]
    for status, expected in (("to_review", "a"), ("verified", "b"), ("none", "c")):
        page = list_tenders(pg_session, report_status=status)  # type: ignore[arg-type]
        found = [r.tender.publication_number for r in page.items]
        assert found == [expected]


def test_cpv_prefix_filter(pg_session: Session) -> None:
    _add(pg_session, "a", cpv_codes=["72000000", "30213000"])
    _add(pg_session, "b", cpv_codes=["30213000"])
    assert [r.tender.publication_number for r in list_tenders(pg_session, cpv="72").items] == ["a"]
    assert list_tenders(pg_session, cpv="302").total == 2


def test_huge_offset_is_rejected_before_postgres(pg_session: Session) -> None:
    with pytest.raises(ValueError, match="page troppo grande"):
        list_tenders(pg_session, page=10**15)
