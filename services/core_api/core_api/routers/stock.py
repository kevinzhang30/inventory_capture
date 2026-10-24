from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from core_api.deps import any_user
from core_api.errors import ApiError
from core_api.schemas import Me, Stock
from core_api.services.stock_cache import get_stock
from inventory_common.auth import Principal
from inventory_common.db import connection

router = APIRouter()


@router.get("/me", response_model=Me)
def me(p: Principal = Depends(any_user)) -> dict[str, Any]:
    return {"user_id": p.user_id, "email": p.email, "groups": sorted(p.groups)}


@router.get("/stock/{sku}", response_model=Stock)
def stock(sku: str, _: Principal = Depends(any_user)) -> dict[str, Any]:
    return get_stock(sku)


@router.get("/parts/{sku}")
def part(sku: str, _: Principal = Depends(any_user)) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(
            """SELECT p.sku, p.part_number, p.name, p.category, p.supplier_id, s.name AS supplier_name, p.uom,
                      p.reorder_point, p.updated_at
               FROM part p LEFT JOIN supplier s USING (supplier_id) WHERE p.sku = %s""",
            (sku,),
        ).fetchone()
        conn.rollback()
    if row is None:
        raise ApiError(404, "not_found", f"unknown sku {sku}")
    return dict(row) | {"stock": get_stock(sku)}
