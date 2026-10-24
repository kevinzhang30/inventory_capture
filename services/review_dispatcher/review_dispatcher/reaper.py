"""Review lease reaper (scheduled every minute; locally `python -m review_dispatcher.reaper --loop`).

(a) claimed tasks whose lease expired and whose Redis lease key is gone → back to ready + ZADD
(b) ready tasks missing from review:ready (e.g. after a Redis flush) → ZADD NX
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from inventory_common import keys
from inventory_common.db import connection, transaction
from inventory_common.log import emit_metric, get_logger
from inventory_common.redis_client import get_redis

log = get_logger(__name__)
PAGE = 1000


def requeue_expired() -> int:
    r = get_redis()
    with connection() as conn:
        rows = conn.execute(
            """SELECT task_id::text AS task_id FROM review_task
               WHERE status = 'claimed' AND lease_expires_at < now() LIMIT %s""",
            (PAGE,),
        ).fetchall()
        conn.rollback()
    expired = [row["task_id"] for row in rows if not r.exists(keys.review_lease(row["task_id"]))]
    if not expired:
        return 0
    with transaction() as conn:
        requeued = conn.execute(
            """UPDATE review_task SET status = 'ready', claimed_by = NULL, claimed_at = NULL, lease_expires_at = NULL
               WHERE task_id = ANY(%s::uuid[]) AND status = 'claimed' AND lease_expires_at < now()
               RETURNING task_id::text AS task_id, priority, created_at""",
            (expired,),
        ).fetchall()
    if requeued:
        r.zadd(keys.REVIEW_READY, {t["task_id"]: keys.review_score(t["priority"], t["created_at"]) for t in requeued},
               nx=True)
    return len(requeued)


def reconcile_ready() -> int:
    r = get_redis()
    added = 0
    last = "00000000-0000-0000-0000-000000000000"
    while True:
        with connection() as conn:
            rows = conn.execute(
                """SELECT task_id::text AS task_id, priority, created_at FROM review_task
                   WHERE status = 'ready' AND task_id > %s::uuid ORDER BY task_id LIMIT %s""",
                (last, PAGE),
            ).fetchall()
            conn.rollback()
        if not rows:
            return added
        scores = {str(t["task_id"]): keys.review_score(t["priority"], t["created_at"]) for t in rows}
        added += int(r.zadd(keys.REVIEW_READY, scores, nx=True))
        last = rows[-1]["task_id"]


def run_once() -> dict[str, int]:
    out = {"requeued": requeue_expired(), "reconciled": reconcile_ready()}
    if out["requeued"]:
        emit_metric("ReviewLeasesExpired", out["requeued"])
    if out["reconciled"]:
        emit_metric("ReviewQueueReconciled", out["reconciled"])
    return out


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    return run_once()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=float, default=30)
    args = ap.parse_args()
    while True:
        try:
            result = run_once()
            if any(result.values()):
                log.info("reaper pass", extra=result)
        except Exception:  # noqa: BLE001
            log.exception("reaper pass failed")
        if not args.loop:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
