"""reorder worker (Amazon MQ reorder.request): records the request and queues a notification (same txn)."""

from __future__ import annotations

from typing import Any

from inventory_common.config import settings
from inventory_common.db import transaction
from inventory_common.lambda_events import RmqMessage, rmq_consume
from inventory_common.models import ReorderRequest
from inventory_common.stock import enqueue_command


def record(payload: dict[str, Any], _msg: RmqMessage | None = None) -> bool:
    req = ReorderRequest.model_validate(payload)
    with transaction() as conn:
        row = conn.execute(
            """INSERT INTO reorder_request (command_id, sku, location_id, on_hand_total, reorder_point)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (command_id) DO NOTHING RETURNING request_id""",
            (req.command_id, req.sku, req.location_id, req.on_hand_total, req.reorder_point),
        ).fetchone()
        if row is None:
            return False
        enqueue_command(conn, "notify", {
            "command_id": f"notify:{req.command_id}",
            "channel": "sns" if settings.sns_topic_arn else "log",
            "subject": f"Reorder {req.sku}",
            "message": (f"SKU {req.sku} is at {req.on_hand_total} units, at or below its reorder point of "
                        f"{req.reorder_point}. Request {row['request_id']}."),
        })
        conn.execute("UPDATE reorder_request SET status = 'notified' WHERE request_id = %s", (row["request_id"],))
    return True


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    return rmq_consume(event, record)
