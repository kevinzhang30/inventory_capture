"""core-api: reads (stock, search, dashboard), review workflow, eval results, admin."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core_api import errors
from core_api.routers import admin, dashboard, reviews, search, stock
from core_api.routers import eval as eval_router

app = FastAPI(title="Inventory Capture core-api", version="0.1.0")
errors.install(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["authorization", "content-type", "x-dev-user", "x-dev-groups"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


for r in (stock.router, search.router, dashboard.router, reviews.router, eval_router.router, admin.router):
    app.include_router(r)
