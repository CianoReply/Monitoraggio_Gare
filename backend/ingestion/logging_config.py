"""Log in formato JSON (T1.6): una riga JSON per messaggio, leggibile da strumenti e persone.

Campi: `level`, `time` (ISO 8601 UTC), `module` (nome del logger), `message`; in più
`exception` se presente e i campi passati con `extra={"context": {...}}`.
`configure_logging()` si chiama una volta all'avvio dell'applicazione o del job (T4.1).
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, TextIO

RESERVED_KEYS = ("level", "time", "module", "message", "exception")


class JsonFormatter(logging.Formatter):
    """Formatta ogni record come un oggetto JSON su una riga."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            for key, value in context.items():
                if key not in RESERVED_KEYS:
                    payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int | str = logging.INFO, stream: TextIO | None = None) -> None:
    """Imposta sul logger radice un unico handler con `JsonFormatter` (idempotente)."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        if isinstance(existing.formatter, JsonFormatter):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
