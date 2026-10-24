"""Human review workflow (design §6.3, ADR-005): Postgres owns tasks, Redis holds the ready queue and leases."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from core_api.errors import ApiError
from inventory_common import keys, s3
from inventory_common.auth import Principal
from inventory_common.db import connection, transaction
from inventory_common.log import emit_metric, get_logger
from inventory_common.models import ReviewSubmission
from inventory_common.redis_client import get_redis
from inventory_common.stock import MovementIn, apply_movements, enqueue_event, known_locations, known_skus

log = get_logger(__name__)
MAX_POPS = 50

TASK_SQL = """
SELECT t.task_id, t.extraction_id, e.capture_id, t.reason, t.priority, t.status, t.claimed_by, t.lease_expires_at,
       c.site_id, c.station_id, c.captured_at, c.payload, c.s3_key,
       e.model_id, e.prompt_version, e.min_confidence, e.output
FROM review_task t
JOIN extraction e ON e.extraction_id = t.extraction_id
JOIN capture c ON c.capture_id = e.capture_id
WHERE t.task_id = %s
"""


def _lease_until() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=keys.LEASE_TTL_S)


def load_task(task_id: str) -> dict[str, Any]:
    with connection() as conn:
        row = conn.execute(TASK_SQL, (task_id,)).fetchone()
        conn.rollback()
    if row is None:
        raise ApiError(404, "not_found", f"task {task_id}")
    return {
        "task_id": str(row["task_id"]),
        "extraction_id": str(row["extraction_id"]),
        "capture_id": str(row["capture_id"]),
        "reason": row["reason"],
        "priority": row["priority"],
        "status": row["status"],
        "claimed_by": row["claimed_by"],
        "lease_expires_at": row["lease_expires_at"],
        "image_url": s3.presign_get(row["s3_key"]) if row["s3_key"] else None,
        "capture": {"site_id": row["site_id"], "station_id": row["station_id"],
                    "captured_at": row["captured_at"], "payload": row["payload"]},
        "extraction": {"model_id": row["model_id"], "prompt_version": row["prompt_version"],
                       "min_confidence": float(row["min_confidence"]) if row["min_confidence"] is not None else None,
                       "output": row["output"]},
    }


def claim_next(user: Principal) -> dict[str, Any] | None:
    r = get_redis()
    with connection() as conn:
        mine = conn.execute(
            """SELECT task_id FROM review_task
               WHERE status = 'claimed' AND claimed_by = %s AND lease_expires_at > now()
               ORDER BY claimed_at LIMIT 1""",
            (user.user_id,),
        ).fetchone()
        conn.rollback()
    if mine and r.get(keys.review_lease(str(mine["task_id"]))) == user.user_id:
        return load_task(str(mine["task_id"]))  # resume an open task instead of hoarding a second one

    for _ in range(MAX_POPS):
        popped = r.zpopmin(keys.REVIEW_READY, 1)
        if not popped:
            return None
        task_id = str(popped[0][0])
        if not r.set(keys.review_lease(task_id), user.user_id, nx=True, ex=keys.LEASE_TTL_S):
            continue
        with transaction() as conn:
            row = conn.execute(
                """UPDATE review_task
                   SET status = 'claimed', claimed_by = %s, claimed_at = now(), lease_expires_at = %s
                   WHERE task_id = %s AND status = 'ready' RETURNING task_id""",
                (user.user_id, _lease_until(), task_id),
            ).fetchone()
        if row is None:  # stale queue entry (already claimed or done)
            r.delete(keys.review_lease(task_id))
            continue
        emit_metric("ReviewClaimed", 1)
        return load_task(task_id)
    return None


def _check_lease(task_id: str, user: Principal) -> None:
    if get_redis().get(keys.review_lease(task_id)) != user.user_id:
        raise ApiError(409, "lease_lost", "this task is no longer claimed by you")


def renew(task_id: str, user: Principal) -> datetime:
    _check_lease(task_id, user)
    get_redis().expire(keys.review_lease(task_id), keys.LEASE_TTL_S)
    until = _lease_until()
    with transaction() as conn:
        conn.execute(
            "UPDATE review_task SET lease_expires_at = %s WHERE task_id = %s AND claimed_by = %s",
            (until, task_id, user.user_id),
        )
    return until


def release(task_id: str, user: Principal) -> None:
    _check_lease(task_id, user)
    with transaction() as conn:
        row = conn.execute(
            """UPDATE review_task SET status = 'ready', claimed_by = NULL, claimed_at = NULL, lease_expires_at = NULL
               WHERE task_id = %s AND status = 'claimed' AND claimed_by = %s
               RETURNING priority, created_at""",
            (task_id, user.user_id),
        ).fetchone()
    r = get_redis()
    r.delete(keys.review_lease(task_id))
    if row:
        r.zadd(keys.REVIEW_READY, {task_id: keys.review_score(row["priority"], row["created_at"])}, nx=True)


def submit(task_id: str, user: Principal, sub: ReviewSubmission) -> list[dict[str, Any]]:
    _check_lease(task_id, user)
    with transaction() as conn:
        task = conn.execute(
            """SELECT t.task_id, t.extraction_id, e.capture_id, c.captured_at, c.site_id, c.status AS capture_status
               FROM review_task t JOIN extraction e USING (extraction_id) JOIN capture c USING (capture_id)
               WHERE t.task_id = %s AND t.status = 'claimed' AND t.claimed_by = %s
               FOR UPDATE OF t""",
            (task_id, user.user_id),
        ).fetchone()
        if task is None:
            raise ApiError(409, "lease_lost", "task is not claimed by you")
        skus = known_skus(conn, [li.sku for li in sub.line_items])
        locs = known_locations(conn, [li.location_id for li in sub.line_items])
        problems = [
            {"line_no": li.line_no, "field": f, "error": f"unknown {f}"}
            for li in sub.line_items
            for f, ok in (("sku", li.sku in skus), ("location_id", li.location_id in locs))
            if not ok
        ] + [{"line_no": li.line_no, "field": "qty", "error": "qty must be positive"}
             for li in sub.line_items if li.qty <= 0]
        if len({li.line_no for li in sub.line_items}) != len(sub.line_items):
            problems.append({"line_no": None, "field": "line_no", "error": "duplicate line_no"})
        if problems:
            raise ApiError(422, "validation_error", problems)

        cid = str(task["capture_id"])
        corrected = sub.model_dump(mode="json", exclude={"notes"})
        conn.execute(
            """INSERT INTO ground_truth (extraction_id, task_id, corrected, reviewer_id)
               VALUES (%s, %s, %s::jsonb, %s) ON CONFLICT (extraction_id) DO NOTHING""",
            (task["extraction_id"], task_id, json.dumps(corrected), user.user_id),
        )
        movements = apply_movements(
            conn,
            [MovementIn(sku=li.sku, location_id=li.location_id, qty_delta=li.qty, type="receipt",
                        idempotency_key=f"{cid}:{li.line_no}", source_capture_id=cid)
             for li in sub.line_items],
            captured_at=task["captured_at"].isoformat(),
        )
        conn.execute(
            "UPDATE review_task SET status = 'done', completed_at = now(), lease_expires_at = NULL WHERE task_id = %s",
            (task_id,),
        )
        conn.execute("UPDATE capture SET status = 'reviewed' WHERE capture_id = %s", (cid,))
        enqueue_event(conn, cid, {
            "type": "document.extracted", "capture_id": cid, "extraction_id": str(task["extraction_id"]),
            "site_id": task["site_id"], "supplier": sub.supplier, "po_number": sub.po_number, "raw_text": "",
            "line_items": [{"line_no": li.line_no, "sku": li.sku, "part_number": li.part_number, "qty": li.qty,
                            "description": None} for li in sub.line_items],
            "status": "reviewed", "captured_at": task["captured_at"].isoformat(),
        })
    get_redis().delete(keys.review_lease(task_id))
    emit_metric("ReviewSubmitted", 1)
    return movements


def stats() -> dict[str, int]:
    ready = int(get_redis().zcard(keys.REVIEW_READY))
    with connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) FILTER (WHERE status = 'claimed') AS claimed,
                      COUNT(*) FILTER (WHERE status = 'done' AND completed_at >= date_trunc('day', now())) AS done_today
               FROM review_task"""
        ).fetchone()
        conn.rollback()
    assert row is not None
    return {"ready": ready, "claimed": int(row["claimed"]), "done_today": int(row["done_today"])}

