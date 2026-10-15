"""Controlli statici dei workflow GitHub Actions (T3.6). Senza rete e senza GitHub.

PyYAML non è dichiarato in pyproject.toml: arriva come dipendenza transitiva di
openapi-spec-validator (dev) ed è usato solo qui, nei test.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # YAML 1.1 legge la chiave `on` come booleano True.
    if True in data:
        data["on"] = data.pop(True)
    return data


def _run_commands(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


@pytest.fixture(scope="module")
def ci() -> dict[str, Any]:
    return _load("ci.yml")


def test_ci_runs_on_pull_requests_to_main_and_develop(ci: dict[str, Any]) -> None:
    assert set(ci["on"]["pull_request"]["branches"]) == {"main", "develop"}


def test_ci_jobs_are_defined(ci: dict[str, Any]) -> None:
    assert set(ci["jobs"]) == {"lint", "test", "test-postgres", "docker-build"}
    for job in ci["jobs"].values():
        assert job["runs-on"] == "ubuntu-latest"


def test_lint_job_checks_and_format_checks(ci: dict[str, Any]) -> None:
    commands = _run_commands(ci["jobs"]["lint"])
    assert "ruff check ." in commands
    assert "ruff format --check ." in commands


def test_test_job_runs_contract_conformance_and_full_suite(ci: dict[str, Any]) -> None:
    commands = _run_commands(ci["jobs"]["test"])
    assert any("test_api_contract.py" in c and "test_api_skeleton.py" in c for c in commands)
    assert "pytest" in commands


def test_every_python_job_installs_dev_dependencies(ci: dict[str, Any]) -> None:
    for name in ("lint", "test", "test-postgres"):
        assert 'pip install -e ".[dev]"' in _run_commands(ci["jobs"][name]), name


def test_postgres_job_sets_test_postgres_url_for_its_service(ci: dict[str, Any]) -> None:
    job = ci["jobs"]["test-postgres"]
    service = job["services"]["postgres"]
    assert service["image"].startswith("postgres:")
    assert "5432:5432" in service["ports"]
    url = job["env"]["TEST_POSTGRES_URL"]
    assert url.startswith("postgresql+psycopg://")
    assert service["env"]["POSTGRES_USER"] in url
    assert service["env"]["POSTGRES_PASSWORD"] in url
    assert service["env"]["POSTGRES_DB"] in url
    assert "--health-cmd" in service["options"]
    assert any("-k postgres" in c for c in _run_commands(job))


def test_docker_build_is_skipped_until_dockerfile_exists(ci: dict[str, Any]) -> None:
    assert "hashFiles('Dockerfile')" in ci["jobs"]["docker-build"]["if"]
    assert any(c.startswith("docker build") for c in _run_commands(ci["jobs"]["docker-build"]))


def test_ci_has_read_only_permissions(ci: dict[str, Any]) -> None:
    assert ci["permissions"] == {"contents": "read"}


def test_claude_workflow_triggers_on_mentions() -> None:
    claude = _load("claude.yml")
    assert {"issue_comment", "pull_request_review_comment", "pull_request_review", "issues"} <= set(
        claude["on"]
    )
    condition = claude["jobs"]["claude"]["if"]
    assert "@claude" in condition
    uses = [s["uses"] for s in claude["jobs"]["claude"]["steps"] if "uses" in s]
    assert any(u.startswith("anthropics/claude-code-action@") for u in uses)


def test_claude_workflow_declares_unverified_authentication() -> None:
    text = (WORKFLOWS / "claude.yml").read_text(encoding="utf-8")
    assert "DA VERIFICARE" in text
    assert "${{ secrets." in text


def test_no_secret_value_is_committed() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "sk-ant-" not in text, path.name
