from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends

from core_api.deps import admin
from core_api.errors import ApiError
from core_api.schemas import PartIn
from inventory_common import app_settings
from inventory_common.auth import Principal
from inventory_common.db import transaction
from inventory_common.stock import enqueue_event

router = APIRouter(prefix="/admin")


@router.put("/parts/{sku}")
def upsert_part(sku: str, part: PartIn, _: Principal = Depends(admin)) -> dict[str, Any]:
    with transaction() as conn:
        if part.supplier_id and not conn.execute(
            "SELECT 1 FROM supplier WHERE supplier_id = %s", (part.supplier_id,)
        ).fetchone():
            raise ApiError(422, "validation_error", f"unknown supplier {part.supplier_id}")
        row = conn.execute(
            """INSERT INTO part (sku, part_number, name, category, supplier_id, uom, reorder_point)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (sku) DO UPDATE SET part_number = EXCLUDED.part_number, name = EXCLUDED.name,
                 category = EXCLUDED.category, supplier_id = EXCLUDED.supplier_id, uom = EXCLUDED.uom,
                 reorder_point = EXCLUDED.reorder_point, updated_at = now()
               RETURNING sku, part_number, name, category, supplier_id, uom, reorder_point,
                 (SELECT name FROM supplier s WHERE s.supplier_id = part.supplier_id) AS supplier_name""",
            (sku, part.part_number, part.name, part.category, part.supplier_id, part.uom, part.reorder_point),
        ).fetchone()
        assert row is not None  # upsert always returns a row
        enqueue_event(conn, sku, {"type": "part.upserted", **row})
    return dict(row)


@router.put("/settings/{key}")
def put_setting(key: str, value: Any = Body(..., embed=True), _: Principal = Depends(admin)) -> dict[str, Any]:  # noqa: B008
    if key == "confidence_threshold" and not (isinstance(value, int | float) and 0 <= value <= 1):
        raise ApiError(422, "validation_error", "confidence_threshold must be within [0, 1]")
    with transaction() as conn:
        conn.execute(
            """INSERT INTO app_setting (key, value) VALUES (%s, %s::jsonb)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
            (key, json.dumps(value)),
        )
    app_settings.invalidate(key)
    return {"key": key, "value": value}
