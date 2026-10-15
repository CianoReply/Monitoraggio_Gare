"""Controlli statici dei workflow GitHub Actions (T3.6). Senza rete e senza GitHub.

PyYAML non è dichiarato in pyproject.toml: arriva come dipendenza transitiva di
openapi-spec-validator (dev) ed è usato solo qui, nei test.
"""

import re
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
    assert "pytest -m contract -q" in commands
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
    # Solo i test PostgreSQL: l'intera suite gira già nel job `test`.
    assert [c for c in _run_commands(job) if c.startswith("pytest")] == [
        "pytest backend/tests/domain -k postgres -rA"
    ]


def test_docker_build_is_skipped_until_dockerfile_exists(ci: dict[str, Any]) -> None:
    assert "hashFiles('Dockerfile')" in ci["jobs"]["docker-build"]["if"]
    assert any(c.startswith("docker build") for c in _run_commands(ci["jobs"]["docker-build"]))


def test_ci_has_read_only_permissions(ci: dict[str, Any]) -> None:
    assert ci["permissions"] == {"contents": "read"}


def test_every_job_has_a_timeout(ci: dict[str, Any]) -> None:
    claude = _load("claude.yml")
    for job in [*ci["jobs"].values(), *claude["jobs"].values()]:
        assert 0 < job["timeout-minutes"] <= 15


def test_python_version_is_at_least_3_12(ci: dict[str, Any]) -> None:
    versions = [
        step["with"]["python-version"]
        for job in ci["jobs"].values()
        for step in job["steps"]
        if str(step.get("uses", "")).startswith("actions/setup-python")
    ]
    assert versions
    for version in versions:
        major, minor = (int(part) for part in str(version).split(".")[:2])
        assert (major, minor) >= (3, 12)


def test_claude_workflow_triggers_on_mentions() -> None:
    claude = _load("claude.yml")
    assert {"issue_comment", "pull_request_review_comment", "pull_request_review", "issues"} <= set(
        claude["on"]
    )
    condition = claude["jobs"]["claude"]["if"]
    assert "@claude" in condition
    uses = [s["uses"] for s in claude["jobs"]["claude"]["steps"] if "uses" in s]
    assert any(u.startswith("anthropics/claude-code-action@") for u in uses)


def test_claude_workflow_is_behind_switch_and_restricted_to_members() -> None:
    condition = _load("claude.yml")["jobs"]["claude"]["if"]
    assert condition.startswith("vars.CLAUDE_ENABLED == 'true'")
    assert condition.count("author_association") == 4  # un controllo per ogni evento
    for association in ("OWNER", "MEMBER", "COLLABORATOR"):
        assert association in condition
    for outsider in ("CONTRIBUTOR", "NONE", "FIRST_TIME_CONTRIBUTOR"):
        assert outsider not in condition


def test_claude_workflow_permissions_are_minimal() -> None:
    permissions = _load("claude.yml")["jobs"]["claude"]["permissions"]
    assert permissions == {"contents": "read", "pull-requests": "write", "issues": "write"}


def test_claude_workflow_declares_unverified_authentication() -> None:
    text = (WORKFLOWS / "claude.yml").read_text(encoding="utf-8")
    assert "DA VERIFICARE" in text
    assert "SHA" in text  # promemoria per fissare l'action


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for key, value in node.items() for s in (*_strings(key), *_strings(value))]
    if isinstance(node, list):
        return [s for value in node for s in _strings(value)]
    return []


@pytest.mark.parametrize("name", ["ci.yml", "claude.yml"])
def test_secrets_are_only_used_inside_expressions(name: str) -> None:
    for value in _strings(_load(name)):
        for match in re.finditer(r"secrets\.", value):
            before = value[: match.start()]
            assert before.count("${{") > before.count("}}"), value


@pytest.mark.parametrize("name", ["ci.yml", "claude.yml"])
def test_no_pull_request_target(name: str) -> None:
    assert "pull_request_target" not in _load(name)["on"]
    code = [
        line
        for line in (WORKFLOWS / name).read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    assert not any("pull_request_target" in line for line in code)


def test_no_secret_value_is_committed() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "sk-ant-" not in text, path.name


def test_contract_marker_selects_conformance_tests() -> None:
    root = Path(__file__).resolve().parent
    for name in ("test_api_contract.py", "test_api_skeleton.py"):
        assert "pytestmark = pytest.mark.contract" in (root / name).read_text(encoding="utf-8")
    assert "@pytest.mark.contract" in (root / "test_api_tenders.py").read_text(encoding="utf-8")
