"""Response models (docs/CONTRACTS.md §2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StockLocation(BaseModel):
    location_id: str
    on_hand: int
    version: int


class Stock(BaseModel):
    sku: str
    on_hand_total: int
    locations: list[StockLocation]
    source: str


class Me(BaseModel):
    user_id: str
    email: str | None
    groups: list[str]


class Facet(BaseModel):
    key: str
    count: int


class SearchResult(BaseModel):
    total: int
    items: list[dict[str, Any]]
    facets: dict[str, list[Facet]]


class ReviewTask(BaseModel):
    task_id: str
    extraction_id: str
    capture_id: str
    reason: str
    priority: int
    status: str
    claimed_by: str | None
    lease_expires_at: datetime | None
    image_url: str | None
    capture: dict[str, Any]
    extraction: dict[str, Any]


class ReviewStats(BaseModel):
    ready: int
    claimed: int
    done_today: int


class LeaseInfo(BaseModel):
    lease_expires_at: datetime


class EvalRun(BaseModel):
    run_id: str
    kind: str
    model_id: str
    prompt_version: str
    sample_size: int
    metrics: dict[str, Any]
    created_at: datetime


class EvalRuns(BaseModel):
    items: list[EvalRun]


class PartIn(BaseModel):
    part_number: str
    name: str
    category: str
    supplier_id: str | None = None
    uom: str = "ea"
    reorder_point: int = 0
