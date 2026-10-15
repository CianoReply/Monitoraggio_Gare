"""Test delle migrazioni Alembic su SQLite temporaneo (nessuna rete, nessun Postgres)."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from backend.domain.models import Base

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "domain" / "alembic.ini"
TABLES = {"tenders", "documents", "reports", "report_fields", "ingestion_runs"}


def _config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_upgrade_head_creates_all_tables_and_indexes(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    command.upgrade(_config(url), "head")
    insp = inspect(create_engine(url))
    assert TABLES <= set(insp.get_table_names())

    tender_idx = {i["name"]: i for i in insp.get_indexes("tenders")}
    assert tender_idx["ix_tenders_publication_number"]["unique"]
    for col in ("submission_deadline", "relevance_score", "publication_date"):
        assert f"ix_tenders_{col}" in tender_idx
    assert any(u["column_names"] == ["tender_id"] for u in insp.get_unique_constraints("reports"))
    assert "ix_ingestion_runs_run_date" in {i["name"] for i in insp.get_indexes("ingestion_runs")}
    assert "run_date" in {c["name"] for c in insp.get_columns("ingestion_runs")}


def test_downgrade_base_removes_all_tables(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    cfg = _config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert not TABLES & set(inspect(create_engine(url)).get_table_names())


def test_migration_matches_models(tmp_path: Path) -> None:
    """Dopo `upgrade head` i modelli non devono differire dallo schema."""
    url = f"sqlite:///{tmp_path / 'test.db'}"
    command.upgrade(_config(url), "head")
    with create_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
