"""Il guardiano dei test PostgreSQL funziona anche senza un database (non è saltato)."""

import pytest

from backend.tests.domain.test_postgres import require_test_database


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://radar:pwd@localhost:5432/radar_test",
        "postgresql+psycopg://radar@db/ci_test",
    ],
)
def test_database_names_ending_with_test_are_accepted(url: str) -> None:
    require_test_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://radar:pwd@localhost:5432/radar",
        "postgresql+psycopg://radar:pwd@localhost:5432/radar_test_old",
        "postgresql+psycopg://radar:pwd@localhost:5432/",
        "postgresql+psycopg://radar:pwd@localhost:5432",
    ],
)
def test_other_database_names_are_refused(url: str) -> None:
    with pytest.raises(pytest.fail.Exception, match="_test"):
        require_test_database(url)
