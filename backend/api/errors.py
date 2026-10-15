"""Errori applicativi e handler che li rendono nel formato `{ "error", "message" }`."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.schemas import Error


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


async def _validation_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    parts = []
    for item in exc.errors():
        location = ".".join(str(p) for p in item["loc"] if p not in ("query", "path", "body"))
        message = str(item["msg"]).removeprefix("Value error, ")
        parts.append(f"{location}: {message}" if location else message)
    return _response(422, "validation_error", "; ".join(parts) or "Richiesta non valida.")


async def _http_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = "not_found" if exc.status_code == 404 else "http_error"
    return _response(exc.status_code, code, str(exc.detail))


def register_error_handlers(app: FastAPI) -> None:
    """Registra gli handler: tutti gli errori escono come `{ "error", "message" }`."""
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
