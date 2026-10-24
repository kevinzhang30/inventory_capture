"""Uniform error envelope: {"error": "<code>", "detail": ...}."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from inventory_common.log import get_logger

log = get_logger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: Any = None):
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": exc.code, "detail": exc.detail}, status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse({"error": code, "detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": "validation_error", "detail": exc.errors()}, status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse({"error": "internal_error", "detail": None}, status_code=500)
