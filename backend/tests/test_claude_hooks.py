"""Test degli hook di Claude Code in `.claude/hooks/` (T0.3).

Gli script non fanno parte del pacchetto `backend`: si caricano dal percorso del file.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "hooks"


def load_hook(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HOOKS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


protect = load_hook("protect_files")
run_tests = load_hook("run_tests")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".env", True),
        ("C:\\repo\\.env", True),
        ("/repo/.env.local", True),
        (".env.example", False),
        ("backend/.venv/x.py", False),
        ("backend/domain/environment.py", False),
    ],
)
def test_is_env_file(path: str, expected: bool) -> None:
    assert protect.is_env_file(path) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/API_CONTRACT.yaml", True),
        ("C:\\repo\\docs\\ARCHITECTURE.md", True),
        ("docs/TASKS.md", False),
    ],
)
def test_is_shared_doc(path: str, expected: bool) -> None:
    assert protect.is_shared_doc(path) is expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("echo x > .env", True),
        ("cat .env", True),
        ("cp .env.example .env.local", True),
        ("cat .env.example", False),
        (".venv/Scripts/python -m pytest", False),
        ("python -c 'import os; os.environ'", False),
    ],
)
def test_command_touches_env(command: str, expected: bool) -> None:
    assert protect.command_touches_env(command) is expected


def test_decide_blocks_env_edit() -> None:
    code, text = protect.decide({"tool_name": "Write", "tool_input": {"file_path": ".env"}})
    assert code == 2
    assert ".env" in text


def test_decide_blocks_env_redirect_in_bash() -> None:
    code, _ = protect.decide({"tool_name": "Bash", "tool_input": {"command": "echo x > .env"}})
    assert code == 2


def test_decide_asks_for_shared_doc() -> None:
    code, text = protect.decide(
        {"tool_name": "Edit", "tool_input": {"file_path": "docs/ARCHITECTURE.md"}}
    )
    assert code == 0
    assert json.loads(text)["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_decide_allows_normal_edit() -> None:
    event = {"tool_name": "Edit", "tool_input": {"file_path": "backend/api/main.py"}}
    assert protect.decide(event) == (0, "")


def test_protect_files_script_exit_code() -> None:
    event = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo x >> .env"}})
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / "protect_files.py")],
        input=event,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Bloccato" in result.stderr


def test_select_test_targets_uses_module_folder(tmp_path: Path) -> None:
    (tmp_path / "backend" / "tests" / "domain").mkdir(parents=True)
    changed = ["backend/domain/models.py", "backend/api/main.py"]
    assert run_tests.select_test_targets(tmp_path, changed) == ["backend/tests/domain"]


def test_select_test_targets_falls_back_to_full_suite(tmp_path: Path) -> None:
    assert run_tests.select_test_targets(tmp_path, ["backend/api/main.py"]) == []


def test_python_executable_prefers_venv(tmp_path: Path) -> None:
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()
    assert run_tests.python_executable(tmp_path) == str(venv_python)


def test_changed_python_files_outside_git_is_empty(tmp_path: Path) -> None:
    assert run_tests.changed_python_files(tmp_path) == []


def test_run_tests_skips_when_stop_hook_active() -> None:
    result = subprocess.run(
        [sys.executable, str(HOOKS_DIR / "run_tests.py")],
        input=json.dumps({"stop_hook_active": True}),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_main_checkout_dir_outside_git_is_none(tmp_path: Path) -> None:
    assert run_tests.main_checkout_dir(tmp_path) is None


def test_python_executable_finds_venv_of_main_checkout(tmp_path: Path) -> None:
    main_dir = tmp_path / "main"
    worktree = tmp_path / "worktree"
    subprocess.run(["git", "init", "-q", str(main_dir)], check=True)
    subprocess.run(
        ["git", "-C", str(main_dir), "commit", "-q", "--allow-empty", "-m", "init"],
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        },
    )
    subprocess.run(["git", "-C", str(main_dir), "worktree", "add", "-q", str(worktree)], check=True)
    venv_python = main_dir / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()
    assert Path(run_tests.python_executable(worktree)) == venv_python.resolve()
