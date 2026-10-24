"""cache-updater Lambda (MSK inventory.events): version-checked write-through of stock levels into Redis."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from inventory_common.lambda_events import iter_kafka_records
from inventory_common.log import emit_metric, get_logger
from inventory_common.redis_client import write_stock

log = get_logger(__name__)


def latest_per_location(events: list[dict[str, Any]]) -> dict[str, list[tuple[str, int, int]]]:
    """{sku: [(location_id, on_hand, version)]} keeping only the highest version per (sku, location)."""
    best: dict[tuple[str, str], tuple[int, int]] = {}
    for e in events:
        k = (e["sku"], e["location_id"])
        if k not in best or e["version"] > best[k][1]:
            best[k] = (int(e["on_hand"]), int(e["version"]))
    out: dict[str, list[tuple[str, int, int]]] = {}
    for (sku, loc), (on_hand, ver) in best.items():
        out.setdefault(sku, []).append((loc, on_hand, ver))
    return out


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    changes: list[dict[str, Any]] = []
    for rec in iter_kafka_records(event):
        try:
            e = rec.json()
        except ValueError:
            log.error("undecodable event skipped", extra={"partition": rec.partition, "offset": rec.offset})
            continue
        if isinstance(e, dict) and e.get("type") == "stock.changed":
            changes.append(e)
    applied = skipped_cold = 0
    for sku, rows in latest_per_location(changes).items():
        n = write_stock(sku, rows, fill=False)
        if n < 0:
            skipped_cold += 1
        else:
            applied += n
    now = datetime.now(UTC)
    latencies = [
        (now - datetime.fromisoformat(e["captured_at"])).total_seconds() * 1000
        for e in changes
        if e.get("captured_at")
    ]
    if latencies:
        # Design §9: end-to-end scan → visible latency, stamped at capture and measured at cache write.
        emit_metric("ScanToVisibleLatencyMax", max(latencies), "Milliseconds")
        emit_metric("ScanToVisibleLatencyAvg", sum(latencies) / len(latencies), "Milliseconds")
    return {"events": len(changes), "applied": applied, "cold_skus": skipped_cold}
