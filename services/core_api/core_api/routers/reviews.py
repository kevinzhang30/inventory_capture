from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response

from core_api.deps import reviewer
from core_api.schemas import LeaseInfo, ReviewStats, ReviewTask
from core_api.services import reviews as svc
from inventory_common.auth import Principal
from inventory_common.models import ReviewSubmission

router = APIRouter(prefix="/reviews")


@router.post("/next", response_model=ReviewTask, responses={204: {"description": "queue empty"}})
def claim_next(p: Principal = Depends(reviewer)) -> Any:
    task = svc.claim_next(p)
    return task if task is not None else Response(status_code=204)


@router.get("/stats", response_model=ReviewStats)
def stats(_: Principal = Depends(reviewer)) -> dict[str, int]:
    return svc.stats()


@router.get("/{task_id}", response_model=ReviewTask)
def get_task(task_id: str, _: Principal = Depends(reviewer)) -> dict[str, Any]:
    return svc.load_task(task_id)


@router.post("/{task_id}/renew", response_model=LeaseInfo)
def renew(task_id: str, p: Principal = Depends(reviewer)) -> dict[str, Any]:
    return {"lease_expires_at": svc.renew(task_id, p)}


@router.post("/{task_id}/release")
def release(task_id: str, p: Principal = Depends(reviewer)) -> dict[str, str]:
    svc.release(task_id, p)
    return {"status": "ready"}


@router.post("/{task_id}/submit")
def submit(task_id: str, body: ReviewSubmission, p: Principal = Depends(reviewer)) -> dict[str, Any]:
    return {"status": "done", "movements": svc.submit(task_id, p, body)}
