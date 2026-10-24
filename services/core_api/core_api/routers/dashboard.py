from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from core_api.deps import any_user
from core_api.errors import ApiError
from inventory_common import s3
from inventory_common.auth import Principal
from inventory_common.db import connection

router = APIRouter()


@router.get("/dashboard/summary")
def summary(_: Principal = Depends(any_user)) -> dict[str, Any]:
    with connection() as conn:
        counts = conn.execute(
            """SELECT
                 (SELECT COUNT(*) FROM capture WHERE received_at > now() - interval '1 hour') AS captures_last_hour,
                 (SELECT COUNT(*) FROM review_task WHERE status = 'ready') AS pending_reviews,
                 (SELECT COUNT(*) FROM review_task WHERE status = 'claimed') AS claimed_reviews"""
        ).fetchone()
        low = conn.execute(
            """SELECT p.sku, p.name, COALESCE(SUM(sl.on_hand), 0)::int AS on_hand_total, p.reorder_point
               FROM part p LEFT JOIN stock_level sl ON sl.sku = p.sku
               WHERE p.reorder_point > 0
               GROUP BY p.sku HAVING COALESCE(SUM(sl.on_hand), 0) <= p.reorder_point
               ORDER BY COALESCE(SUM(sl.on_hand), 0)::float / p.reorder_point, p.sku LIMIT 20"""
        ).fetchall()
        recent = conn.execute(
            """SELECT movement_id, sku, location_id, qty_delta, type, created_at
               FROM stock_movement ORDER BY movement_id DESC LIMIT 20"""
        ).fetchall()
        conn.rollback()
    return dict(counts or {}) | {"low_stock": low, "recent_movements": recent}


@router.get("/captures/{capture_id}")
def capture(capture_id: str, _: Principal = Depends(any_user)) -> dict[str, Any]:
    with connection() as conn:
        cap = conn.execute("SELECT * FROM capture WHERE capture_id = %s::uuid", (capture_id,)).fetchone()
        if cap is None:
            conn.rollback()
            raise ApiError(404, "not_found", f"capture {capture_id}")
        extractions = conn.execute(
            """SELECT e.extraction_id, e.model_id, e.prompt_version, e.output, e.min_confidence, e.latency_ms,
                      e.input_tokens, e.output_tokens, e.error, e.created_at,
                      gt.corrected AS ground_truth, gt.reviewer_id, t.task_id, t.status AS review_status, t.reason
               FROM extraction e
               LEFT JOIN ground_truth gt ON gt.extraction_id = e.extraction_id
               LEFT JOIN review_task t ON t.extraction_id = e.extraction_id
               WHERE e.capture_id = %s ORDER BY e.created_at""",
            (capture_id,),
        ).fetchall()
        movements = conn.execute(
            "SELECT movement_id, sku, location_id, qty_delta, type, created_at FROM stock_movement "
            "WHERE source_capture_id = %s ORDER BY movement_id",
            (capture_id,),
        ).fetchall()
        conn.rollback()
    return {
        "capture": dict(cap),
        "extractions": extractions,
        "movements": movements,
        "image_url": s3.presign_get(cap["s3_key"]) if cap["s3_key"] else None,
    }
