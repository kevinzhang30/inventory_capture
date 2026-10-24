"""reorder-checker Lambda (MSK inventory.events): emits one reorder.request per SKU per day below reorder point."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from inventory_common import keys, rabbit
from inventory_common.lambda_events import iter_kafka_records
from inventory_common.log import emit_metric, get_logger
from inventory_common.models import ReorderRequest
from inventory_common.redis_client import get_redis

log = get_logger(__name__)


def below_reorder_point(e: dict[str, Any]) -> bool:
    rp = int(e.get("reorder_point") or 0)
    return rp > 0 and int(e.get("on_hand_total", e.get("on_hand", 0))) <= rp


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    latest: dict[str, dict[str, Any]] = {}
    for rec in iter_kafka_records(event):
        try:
            e = rec.json()
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("type") == "stock.changed":
            latest[e["sku"]] = e  # records arrive in per-partition (per-SKU) order
    r = get_redis()
    sent = 0
    for sku, e in latest.items():
        if not below_reorder_point(e):
            continue
        now = datetime.now(UTC)
        key = keys.reorder_sent(sku, now)
        if not r.set(key, "1", nx=True, ex=keys.REORDER_TTL_S):
            continue
        cmd = ReorderRequest(
            command_id=f"reorder:{sku}:{now:%Y%m%d}",
            sku=sku,
            on_hand_total=int(e.get("on_hand_total", e.get("on_hand", 0))),
            reorder_point=int(e["reorder_point"]),
            location_id=e.get("location_id"),
            requested_at=now,
        )
        try:
            rabbit.publish("reorder.request", cmd.model_dump(mode="json"), message_id=cmd.command_id)
        except Exception:
            r.delete(key)  # allow the retried batch to send it
            raise
        sent += 1
    if sent:
        emit_metric("ReorderRequests", sent)
    return {"skus": len(latest), "reorders": sent}
