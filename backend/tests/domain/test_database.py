"""Test di database.py, utcnow, seed.main e del filtro cpv su PostgreSQL (opzionale)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.domain import seed as seed_module
from backend.domain.database import create_db_engine, create_session_factory, get_database_url
from backend.domain.models import Tender, utcnow

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "domain" / "alembic.ini"


def test_get_database_url_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", " sqlite:///x.db ")
    assert get_database_url() == "sqlite:///x.db"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_get_database_url_requires_variable(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(RuntimeError):
        get_database_url()


def test_create_db_engine_and_session_factory() -> None:
    engine = create_db_engine("sqlite://")
    with create_session_factory(engine)() as session:
        assert session.execute(text("SELECT 1")).scalar() == 1
    engine.dispose()


def test_create_db_engine_uses_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    engine = create_db_engine()
    assert engine.url.get_backend_name() == "sqlite"
    engine.dispose()


def test_utcnow_is_timezone_aware_utc() -> None:
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == UTC.utcoffset(now)
    assert abs((datetime.now(UTC) - now).total_seconds()) < 5


def test_seed_main_populates_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{tmp_path / 'seed.db'}"
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    monkeypatch.setenv("DATABASE_URL", url)
    seed_module.main()
    with Session(create_engine(url)) as session:
        assert session.scalar(select(func.count()).select_from(Tender)) == 20
