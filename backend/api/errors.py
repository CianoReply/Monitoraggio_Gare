"""Errori applicativi e handler che li rendono nel formato `{ "error", "message" }`."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.schemas import Error
from backend.domain.reports import (
    FieldNotFoundError,
    ReportAlreadyExistsError,
    ReportError,
    ReportNotFoundError,
    ReportValidationError,
    TenderNotFoundError,
)

# Codice HTTP degli errori del dominio dei report (il codice applicativo è `exc.code`).
REPORT_ERROR_STATUS: dict[type[ReportError], int] = {
    TenderNotFoundError: 404,
    ReportNotFoundError: 404,
    FieldNotFoundError: 404,
    ReportAlreadyExistsError: 409,
    ReportValidationError: 422,
}

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Errore con codice HTTP e codice applicativo stabile."""

    def __init__(self, status_code: int, error: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message


def error_responses(*codes: int) -> dict[int | str, dict]:
    """Dichiara nella documentazione OpenAPI le risposte di errore nel formato unico."""
    return {code: {"model": Error} for code in codes}


def _response(status_code: int, error: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error, "message": message})


async def _api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _response(exc.status_code, exc.error, exc.message)


# Messaggi in italiano per i tipi di errore di validazione più comuni (`{nome}` dal contesto).
VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "campo obbligatorio",
    "extra_forbidden": "campo non previsto",
    "int_parsing": "deve essere un numero intero",
    "int_type": "deve essere un numero intero",
    "int_from_float": "deve essere un numero intero",
    "float_parsing": "deve essere un numero",
    "float_type": "deve essere un numero",
    "finite_number": "deve essere un numero finito",
    "bool_parsing": "deve essere true o false",
    "bool_type": "deve essere true o false",
    "string_type": "deve essere un testo",
    "string_too_short": "troppo corto (minimo {min_length} caratteri)",
    "string_too_long": "troppo lungo (massimo {max_length} caratteri)",
    "string_pattern_mismatch": "formato non valido",
    "greater_than_equal": "deve essere maggiore o uguale a {ge}",
    "greater_than": "deve essere maggiore di {gt}",
    "less_than_equal": "deve essere minore o uguale a {le}",
    "less_than": "deve essere minore di {lt}",
    "too_short": "deve contenere almeno {min_length} elementi",
    "too_long": "deve contenere al massimo {max_length} elementi",
    "literal_error": "valore non ammesso (valori ammessi: {expected})",
    "enum": "valore non ammesso (valori ammessi: {expected})",
    "date_parsing": "data non valida (formato AAAA-MM-GG)",
    "date_type": "data non valida (formato AAAA-MM-GG)",
    "date_from_datetime_parsing": "data non valida (formato AAAA-MM-GG)",
    "datetime_parsing": "data e ora non valide (formato ISO 8601)",
    "datetime_type": "data e ora non valide (formato ISO 8601)",
    "list_type": "deve essere una lista",
    "dict_type": "deve essere un oggetto",
    "model_attributes_type": "deve essere un oggetto",
    "model_type": "deve essere un oggetto",
    "json_invalid": "JSON non valido",
}
HTTP_MESSAGES: dict[int, str] = {
    404: "Risorsa non trovata.",
    405: "Metodo non consentito per questa risorsa.",
}


def _describe_validation_error(item: dict[str, Any]) -> str:
    template = VALIDATION_MESSAGES.get(item["type"])
    if template is None:
        return str(item["msg"]).removeprefix("Value error, ")
    try:
        return template.format(**(item.get("ctx") or {}))
    except (KeyError, IndexError):
        return template.split(" (")[0].split(" {")[0]


async def _validation_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    parts = []
    for item in exc.errors():
        location = ".".join(str(p) for p in item["loc"] if p not in ("query", "path", "body"))
        message = _describe_validation_error(item)
        parts.append(f"{location}: {message}" if location else message)
    return _response(422, "validation_error", "; ".join(parts) or "Richiesta non valida.")


async def _http_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    return _response(exc.status_code, code, HTTP_MESSAGES.get(exc.status_code, str(exc.detail)))


async def _report_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ReportError)
    status = next((s for cls, s in REPORT_ERROR_STATUS.items() if isinstance(exc, cls)), 500)
    return _response(status, exc.code, exc.message)


async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.error("Errore non gestito", exc_info=exc)
    return _response(500, "internal_error", "Errore interno del server.")


def register_error_handlers(app: FastAPI) -> None:
    """Registra gli handler: tutti gli errori escono come `{ "error", "message" }`."""
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(ReportError, _report_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
