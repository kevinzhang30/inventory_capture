from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from core_api.deps import any_user
from core_api.schemas import SearchResult
from core_api.services import search as svc
from inventory_common.auth import Principal

router = APIRouter(prefix="/search")


@router.get("/parts", response_model=SearchResult)
def parts(
    q: str | None = None,
    category: list[str] = Query(default=[]),  # noqa: B008
    supplier: list[str] = Query(default=[]),  # noqa: B008
    site: list[str] = Query(default=[]),  # noqa: B008
    page: int = 1,
    size: int = 20,
    _: Principal = Depends(any_user),
) -> dict[str, Any]:
    return svc.search_parts(q, category, supplier, site, page, size)


@router.get("/documents", response_model=SearchResult)
def documents(
    q: str | None = None,
    supplier: list[str] = Query(default=[]),  # noqa: B008
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    page: int = 1,
    size: int = 20,
    _: Principal = Depends(any_user),
) -> dict[str, Any]:
    return svc.search_documents(q, supplier, date_from, date_to, page, size)
