"""Controlli statici di Dockerfile, docker-compose.yml e .env.example (T0.7). Senza Docker.

PyYAML arriva come dipendenza transitiva di openapi-spec-validator (dev) ed è usato solo nei test.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.api.main import create_app

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    data = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


def _env_example_keys() -> set[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))


def test_compose_has_db_and_api_services(compose: dict[str, Any]) -> None:
    assert set(compose["services"]) == {"db", "api"}
    assert compose["services"]["db"]["image"].startswith("postgres:")
    assert compose["services"]["api"]["build"] == "."


def test_api_waits_for_healthy_database(compose: dict[str, Any]) -> None:
    api, db = compose["services"]["api"], compose["services"]["db"]
    assert api["depends_on"]["db"]["condition"] == "service_healthy"
    assert "pg_isready" in db["healthcheck"]["test"][-1]


def test_api_runs_migrations_then_uvicorn(compose: dict[str, Any]) -> None:
    command = " ".join(compose["services"]["api"]["command"].split())
    migration = "alembic -c backend/domain/alembic.ini upgrade head"
    server = "uvicorn backend.api.main:app --host 0.0.0.0 --port 8000"
    assert migration in command and server in command
    assert command.index(migration) < command.index(server)


def test_api_runs_scheduler_with_a_single_worker(compose: dict[str, Any]) -> None:
    api = compose["services"]["api"]
    assert api["environment"]["ENABLE_SCHEDULER"] == "true"
    assert "INGESTION_SCHEDULE" in api["environment"]
    command = " ".join(api["command"].split())
    assert command.endswith('--workers 1"') or "--workers 1" in command


def test_env_example_documents_scheduler_variables() -> None:
    assert {"ENABLE_SCHEDULER", "INGESTION_SCHEDULE"} <= _env_example_keys()


def test_api_environment_points_to_compose_database(compose: dict[str, Any]) -> None:
    environment = compose["services"]["api"]["environment"]
    url = environment["DATABASE_URL"]
    assert url.startswith("postgresql+psycopg://")
    assert "@db:5432/" in url
    for key in ("CORS_ORIGINS", "TED_API_URL", "TED_CPV_PREFIXES", "DOCUMENTS_DIR"):
        assert key in environment


def test_ports_are_published_on_localhost_only(compose: dict[str, Any]) -> None:
    for name in ("db", "api"):
        assert all(p.startswith("127.0.0.1:") for p in compose["services"][name]["ports"]), name


def test_compose_has_no_literal_secret_and_uses_dev_defaults(compose: dict[str, Any]) -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "${POSTGRES_PASSWORD:-" in text
    assert "sk-ant-" not in text


def test_compose_variables_are_documented_in_env_example() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    variables = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", text))
    assert variables
    assert variables <= _env_example_keys()


def test_env_example_has_no_values() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if re.match(r"^[A-Z][A-Z0-9_]*=", line):
            assert line.split("=", 1)[1] == "", line


def test_dockerfile_installs_project_and_runs_as_non_root(dockerfile: str) -> None:
    assert re.search(r"^FROM python:3\.(1[2-9]|[2-9]\d)", dockerfile, flags=re.MULTILINE)
    assert "COPY backend ./backend" in dockerfile
    assert "pip install ." in dockerfile
    assert re.search(r"^USER app$", dockerfile, flags=re.MULTILINE)
    assert "uvicorn" in dockerfile and "backend.api.main:app" in dockerfile


def test_dockerignore_excludes_secrets_and_environments() -> None:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", ".env.*", ".venv", ".git"):
        assert entry in lines
    assert "!.env.example" in lines


def test_ci_docker_build_job_is_consistent_with_dockerfile() -> None:
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    job = ci["jobs"]["docker-build"]
    assert "hashFiles('Dockerfile')" in job["if"]
    assert (ROOT / "Dockerfile").is_file()
    assert any("docker build" in step.get("run", "") for step in job["steps"])


def test_health_endpoint_responds_ok() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("value", ["", None])
def test_empty_cors_origins_fall_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ORIGINS", value)
    client = TestClient(create_app())
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
