from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from core_api.deps import any_user
from core_api.schemas import EvalRuns
from inventory_common.auth import Principal
from inventory_common.db import connection

router = APIRouter(prefix="/eval")

COLS = "run_id::text AS run_id, kind, model_id, prompt_version, sample_size, metrics, created_at"


@router.get("/runs", response_model=EvalRuns)
def runs(model_id: str | None = None, prompt_version: str | None = None, limit: int = 50,
         _: Principal = Depends(any_user)) -> dict[str, Any]:
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT {COLS} FROM eval_run
                WHERE (%(m)s::text IS NULL OR model_id = %(m)s) AND (%(p)s::text IS NULL OR prompt_version = %(p)s)
                ORDER BY created_at DESC LIMIT %(l)s""",
            {"m": model_id, "p": prompt_version, "l": max(1, min(limit, 500))},
        ).fetchall()
        conn.rollback()
    return {"items": rows}


@router.get("/latest", response_model=EvalRuns)
def latest(_: Principal = Depends(any_user)) -> dict[str, Any]:
    with connection() as conn:
        rows = conn.execute(
            f"""SELECT DISTINCT ON (model_id, prompt_version, kind) {COLS} FROM eval_run
                ORDER BY model_id, prompt_version, kind, created_at DESC"""
        ).fetchall()
        conn.rollback()
    return {"items": rows}
