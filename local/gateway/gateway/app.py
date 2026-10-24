"""Local API Gateway HTTP API emulator on :8080.

POST /uploads and POST /captures → the ingest Lambda handler with a payload-format-2.0 event.
Everything else → the core-api ASGI app, mounted natively.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from gateway.events import build_event, translate_result
from inventory_common.log import get_logger

log = get_logger("gateway")

LambdaHandler = Callable[[dict[str, Any], Any], dict[str, Any]]
INGEST_ROUTES = ("/uploads", "/captures")


def create_app(ingest_handler: LambdaHandler | None = None, core_app: Any = None) -> FastAPI:
    if ingest_handler is None:
        from ingest.handler import handler as ingest_handler  # type: ignore[no-redef]
    if core_app is None:
        from core_api.app import app as core_app
    auth_mode = os.environ.get("GATEWAY_AUTH_MODE", os.environ.get("AUTH_MODE", "dev"))

    app = FastAPI(title="local api gateway")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["GET", "POST", "PUT", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        response = await call_next(request)
        log.info("request", extra={"method": request.method, "path": request.url.path,
                                   "status": response.status_code,
                                   "ms": round((time.perf_counter() - started) * 1000, 1)})
        return response

    async def to_lambda(request: Request) -> Response:
        event = build_event(
            method=request.method,
            path=request.url.path,
            raw_query=request.url.query,
            headers=request.headers.items(),
            body=await request.body(),
            source_ip=request.client.host if request.client else "127.0.0.1",
            route_key=f"{request.method} {request.url.path}",
            auth_mode=auth_mode,
        )
        result = await run_in_threadpool(ingest_handler, event, None)
        status, headers, body, cookies = translate_result(result)
        resp = Response(content=body, status_code=status, headers=headers)
        for c in cookies:
            resp.headers.append("set-cookie", c)
        return resp

    for path in INGEST_ROUTES:
        app.add_api_route(path, to_lambda, methods=["POST"], include_in_schema=False)
    app.mount("/", core_app)
    return app


app = create_app() if os.environ.get("GATEWAY_LAZY") != "1" else None
