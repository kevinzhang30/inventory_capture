"""review-dispatcher Lambda (Amazon MQ review.dispatch): creates review tasks and enqueues them in Redis."""

from __future__ import annotations

from typing import Any

from inventory_common import keys
from inventory_common.db import transaction
from inventory_common.lambda_events import RmqMessage, rmq_consume
from inventory_common.log import get_logger
from inventory_common.models import ReviewDispatch
from inventory_common.redis_client import get_redis

log = get_logger(__name__)


def dispatch(payload: dict[str, Any], _msg: RmqMessage | None = None) -> str | None:
    cmd = ReviewDispatch.model_validate(payload)
    with transaction() as conn:
        conn.execute(
            """INSERT INTO review_task (extraction_id, reason, priority)
               VALUES (%s, %s, %s) ON CONFLICT (extraction_id) DO NOTHING""",
            (str(cmd.extraction_id), cmd.reason, cmd.priority),
        )
        task = conn.execute(
            "SELECT task_id, status, priority, created_at FROM review_task WHERE extraction_id = %s",
            (str(cmd.extraction_id),),
        ).fetchone()
    assert task is not None  # inserted or already present above
    if task["status"] != "ready":
        return None  # redelivered after it was already claimed or completed
    task_id = str(task["task_id"])
    get_redis().zadd(keys.REVIEW_READY, {task_id: keys.review_score(task["priority"], task["created_at"])}, nx=True)
    log.info("review task ready", extra={"task_id": task_id, "reason": cmd.reason, "capture_id": str(cmd.capture_id)})
    return task_id


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    return rmq_consume(event, dispatch)
