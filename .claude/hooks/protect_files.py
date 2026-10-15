"""Hook PreToolUse: protegge i segreti e i file di accordo tra i moduli.

Riceve su stdin il JSON dell'evento (`tool_name`, `tool_input`).
- `.env` e `.env.*` (tranne `.env.example`): modifica e lettura bloccate (exit 2, motivo su stderr),
  sia con Edit/Write sia con un comando Bash che nomina il file (es. `echo x > .env`, `cat .env`).
- `docs/API_CONTRACT.yaml` e `docs/ARCHITECTURE.md`: la modifica non è vietata ma richiede
  la conferma dell'utente (`permissionDecision: "ask"`), perché si cambiano solo su richiesta
  esplicita e con il consenso dei tre dev (CLAUDE.md, ADR-011).
Negli altri casi esce con 0 senza output.
"""

import json
import re
import sys

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHARED_DOCS = ("docs/API_CONTRACT.yaml", "docs/ARCHITECTURE.md")

# `.env` o `.env.<qualcosa>` come nome di file, ma non `.env.example`, `.venv`, `os.environ`.
ENV_IN_COMMAND = re.compile(r"(?<![\w.])\.env(?!\.example\b)(?:\.[\w-]+)?(?![\w])")


def is_env_file(file_path: str) -> bool:
    """Indica se il percorso punta a un file di segreti `.env` (escluso `.env.example`)."""
    name = file_path.replace("\\", "/").rsplit("/", 1)[-1]
    if name == ".env.example":
        return False
    return name == ".env" or name.startswith(".env.")


def is_shared_doc(file_path: str) -> bool:
    """Indica se il percorso è uno dei documenti condivisi tra i moduli."""
    normalized = file_path.replace("\\", "/")
    return any(normalized == doc or normalized.endswith("/" + doc) for doc in SHARED_DOCS)


def command_touches_env(command: str) -> bool:
    """Indica se un comando Bash nomina un file `.env` (escluso `.env.example`)."""
    return ENV_IN_COMMAND.search(command) is not None


def decide(event: dict) -> tuple[int, str]:
    """Restituisce (codice di uscita, testo da stampare) per l'evento ricevuto.

    Con codice 2 il testo va su stderr (blocco); con codice 0 il testo, se presente, è il JSON
    da stampare su stdout.
    """
    tool_name = event.get("tool_name") or ""
    tool_input = event.get("tool_input") or {}

    if tool_name in EDIT_TOOLS:
        file_path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_env_file(file_path):
            return 2, f"Bloccato: {file_path} contiene segreti e non va modificato (CLAUDE.md)."
        if is_shared_doc(file_path):
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": (
                        f"{file_path} è un accordo tra i moduli: si modifica solo su richiesta "
                        "esplicita e con il consenso dei tre dev."
                    ),
                }
            }
            return 0, json.dumps(output, ensure_ascii=False)
    elif tool_name == "Bash" and command_touches_env(tool_input.get("command") or ""):
        return 2, "Bloccato: il comando legge o scrive un file .env con segreti (CLAUDE.md)."
    return 0, ""


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    code, text = decide(event)
    if text:
        print(text, file=sys.stderr if code == 2 else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
