"""Hook Stop: esegue i test quando Claude termina la risposta, se ha modificato codice Python.

Riceve su stdin il JSON dell'evento (campo `stop_hook_active`).
- Se nel working tree non ci sono file `.py` modificati rispetto a HEAD (o nuovi), esce con 0.
- Altrimenti esegue i test del modulo toccato (`backend/tests/<modulo>/` se esiste, altrimenti
  l'intera suite) con il Python dell'ambiente virtuale del progetto, se presente.
- Se i test falliscono esce con 2: Claude Code mostra l'esito a Claude, che continua per correggere.
- Se `stop_hook_active` è vero (Claude sta già continuando per questo hook) esce con 0,
  per non entrare in un ciclo infinito.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

MODULES = ("ingestion", "domain", "api")


def changed_python_files(project_dir: Path) -> list[str]:
    """Elenca i file `.py` modificati o nuovi rispetto a HEAD nel repository."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    paths = [line[3:].split(" -> ")[-1].strip('"') for line in result.stdout.splitlines()]
    return [path for path in paths if path.endswith(".py")]


def select_test_targets(project_dir: Path, changed: list[str]) -> list[str]:
    """Sceglie le cartelle di test dei moduli toccati; l'intera suite se non sono separate."""
    targets: list[str] = []
    for module in MODULES:
        touched = any(path.startswith(f"backend/{module}/") for path in changed)
        module_tests = f"backend/tests/{module}"
        if touched and (project_dir / module_tests).is_dir():
            targets.append(module_tests)
    return targets


def main_checkout_dir(project_dir: Path) -> Path | None:
    """Restituisce la cartella del checkout principale quando `project_dir` è un worktree git."""
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).parent


def python_executable(project_dir: Path) -> str:
    """Restituisce il Python dell'ambiente virtuale del progetto, se esiste.

    Nei worktree l'ambiente virtuale di solito è solo nel checkout principale: si cerca anche lì.
    """
    roots = [project_dir]
    main_dir = main_checkout_dir(project_dir)
    if main_dir is not None and main_dir != project_dir:
        roots.append(main_dir)
    for root in roots:
        for candidate in (".venv/Scripts/python.exe", ".venv/bin/python"):
            path = root / candidate
            if path.exists():
                return str(path)
    return sys.executable


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        event = {}
    if event.get("stop_hook_active"):
        return 0

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ".")
    changed = changed_python_files(project_dir)
    if not changed:
        return 0

    command = [python_executable(project_dir), "-m", "pytest", "-q", "-x"]
    command += select_test_targets(project_dir, changed)
    result = subprocess.run(command, cwd=project_dir, capture_output=True, text=True)
    if result.returncode not in (0, 5):  # 5 = nessun test raccolto
        print("I test falliscono dopo le tue modifiche:", file=sys.stderr)
        print(result.stdout[-3000:] or result.stderr[-3000:], file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
