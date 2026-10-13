"""Hook PostToolUse: esegue `ruff check` sul file .py appena modificato da Claude.

Riceve su stdin il JSON dell'evento (campo `tool_input.file_path`).
Esce con 2 se ruff trova errori: Claude Code mostra a Claude il messaggio su stderr,
così Claude può correggere subito. Esce con 0 negli altri casi.
"""

import json
import shutil
import subprocess
import sys


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    file_path = (event.get("tool_input") or {}).get("file_path") or ""
    if not file_path.endswith(".py"):
        return 0

    ruff = shutil.which("ruff")
    if ruff is None:
        print("Hook ruff: comando 'ruff' non trovato; attiva l'ambiente virtuale.", file=sys.stderr)
        return 1

    result = subprocess.run([ruff, "check", file_path], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ruff check ha trovato problemi in {file_path}:", file=sys.stderr)
        print(result.stdout or result.stderr, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
