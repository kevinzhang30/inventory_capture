"""Exactly-once stock effects: ledger insert + stock_level update + outbox, all in the caller's transaction.

Idempotency: `stock_movement.idempotency_key` is UNIQUE. A redelivered capture hits the constraint
(ON CONFLICT DO NOTHING) and produces no stock change and no outbox event.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from inventory_common.config import settings
from inventory_common.db import Conn


@dataclass(frozen=True)
class MovementIn:
    sku: str
    location_id: str
    qty_delta: int
    type: str  # receipt | adjustment | correction | issue
    idempotency_key: str
    source_capture_id: str | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def enqueue_outbox(
    conn: Conn,
    destination: str,
    topic_or_queue: str,
    msg_key: str | None,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> None:
    assert destination in ("kafka", "rabbitmq")
    conn.execute(
        """INSERT INTO outbox (destination, topic_or_queue, msg_key, payload, headers)
           VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)""",
        (destination, topic_or_queue, msg_key, json.dumps(payload, default=str), json.dumps(headers or {})),
    )


def enqueue_event(conn: Conn, key: str, event: dict[str, Any]) -> None:
    event.setdefault("event_id", str(uuid.uuid4()))
    event.setdefault("occurred_at", now_iso())
    enqueue_outbox(conn, "kafka", settings.topic_inventory_events, key, event)


def enqueue_command(conn: Conn, queue: str, command: dict[str, Any]) -> None:
    command.setdefault("command_id", str(uuid.uuid4()))
    enqueue_outbox(conn, "rabbitmq", queue, command["command_id"], command)


def apply_movements(
    conn: Conn,
    movements: list[MovementIn],
    captured_at: str | None = None,
) -> list[dict[str, Any]]:
    """Apply movements idempotently. Returns the stock.changed events written (empty for duplicates).

    Rows are locked in (sku, location_id) order to avoid deadlocks between concurrent batches."""
    applied: list[dict[str, Any]] = []
    for m in sorted(movements, key=lambda x: (x.sku, x.location_id, x.idempotency_key)):
        row = conn.execute(
            """INSERT INTO stock_movement (sku, location_id, qty_delta, type, source_capture_id, idempotency_key)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (idempotency_key) DO NOTHING
               RETURNING movement_id""",
            (m.sku, m.location_id, m.qty_delta, m.type, m.source_capture_id, m.idempotency_key),
        ).fetchone()
        if row is None:
            continue  # duplicate delivery
        movement_id = row["movement_id"]
        level = conn.execute(
            """INSERT INTO stock_level (sku, location_id, on_hand, version, updated_at)
               VALUES (%s, %s, %s, 1, now())
               ON CONFLICT (sku, location_id) DO UPDATE
                 SET on_hand = stock_level.on_hand + EXCLUDED.on_hand,
                     version = stock_level.version + 1,
                     updated_at = now()
               RETURNING on_hand, version""",
            (m.sku, m.location_id, m.qty_delta),
        ).fetchone()
        agg = conn.execute(
            """SELECT COALESCE(SUM(sl.on_hand), 0) AS total, MAX(p.reorder_point) AS reorder_point
               FROM part p LEFT JOIN stock_level sl ON sl.sku = p.sku
               WHERE p.sku = %s""",
            (m.sku,),
        ).fetchone()
        assert level is not None  # upsert always returns a row
        event = {
            "type": "stock.changed",
            "sku": m.sku,
            "location_id": m.location_id,
            "on_hand": level["on_hand"],
            "version": level["version"],
            "on_hand_total": int(agg["total"]) if agg else level["on_hand"],
            "reorder_point": int(agg["reorder_point"] or 0) if agg else 0,
            "qty_delta": m.qty_delta,
            "movement_id": movement_id,
            "movement_type": m.type,
            "source_capture_id": m.source_capture_id,
            "captured_at": captured_at,
        }
        enqueue_event(conn, m.sku, event)
        applied.append(event)
    return applied


def known_skus(conn: Conn, skus: list[str]) -> set[str]:
    if not skus:
        return set()
    rows = conn.execute("SELECT sku FROM part WHERE sku = ANY(%s)", (list(set(skus)),)).fetchall()
    return {r["sku"] for r in rows}


def known_locations(conn: Conn, location_ids: list[str]) -> set[str]:
    if not location_ids:
        return set()
    rows = conn.execute(
        "SELECT location_id FROM location WHERE location_id = ANY(%s)", (list(set(location_ids)),)
    ).fetchall()
    return {r["location_id"] for r in rows}
