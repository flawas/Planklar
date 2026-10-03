"""Strukturiertes JSON-Logging. Es gelangen nur IDs, Codes und Zahlen ins Log."""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

LOGGER_NAME = "planklar"
_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_CODE_KEY = re.compile(r"^(?:id|code|[a-z0-9_]+_(?:id|code))$")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    """Haftet die Request-ID beim Loggen am Record an (unabhängig vom Formatierzeitpunkt)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    if not any(isinstance(f, RequestIdFilter) for f in logger.filters):
        logger.addFilter(RequestIdFilter())
    if not any(isinstance(h.formatter, JsonFormatter) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)


def _check(key: str, value: object) -> object:
    if isinstance(value, bool | int | float):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str) and _CODE_KEY.fullmatch(key) and _CODE.fullmatch(value):
        return value
    raise ValueError(f"log_event: Feld '{key}' erlaubt nur IDs, Codes und Zahlen")


def log_event(event: str, *, level: int = logging.INFO, **fields: object) -> None:
    """Loggt ein Ereignis. Freitext (Strings ausser IDs/Codes) wird abgewiesen."""
    if not _CODE.fullmatch(event):
        raise ValueError("log_event: Ereignisname muss ein Code sein")
    checked = {k: _check(k, v) for k, v in fields.items()}
    logging.getLogger(LOGGER_NAME).log(level, event, extra={"fields": checked})


def install_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def _log_requests(request: Request, call_next: Any) -> Response:
        request_id = str(uuid.uuid4())
        token = request_id_var.set(request_id)
        try:
            start = time.perf_counter()
            error_code: str | None = None
            try:
                response: Response = await call_next(request)
            except Exception as exc:  # Nachricht bewusst nicht loggen (Nutzerdaten)
                error_code = "internal_error"
                log_event(
                    "unhandled_exception",
                    level=logging.ERROR,
                    error_code=error_code,
                    exception_code=re.sub(r"[^A-Za-z0-9_.:-]", "_", type(exc).__name__)[:64],
                )
                response = JSONResponse(
                    {"error_code": error_code, "request_id": request_id}, status_code=500
                )
            else:
                if response.status_code >= 400:
                    error_code = f"http_{response.status_code}"
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log_event(
                "request",
                method_code=request.method,
                status=response.status_code,
                duration_ms=duration_ms,
                **({"error_code": error_code} if error_code else {}),
            )
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)
