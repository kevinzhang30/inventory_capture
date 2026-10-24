"""Batch publishing logic, independent of Postgres so ordering/failure rules are unit-testable."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BatchResult:
    sent: list[int] = field(default_factory=list)
    failed: dict[int, str] = field(default_factory=dict)


KafkaSend = Callable[[list[dict[str, Any]]], dict[int, str]]
RabbitSend = Callable[[dict[str, Any]], None]


def publish_batch(rows: list[dict[str, Any]], kafka_send: KafkaSend, rabbit_send: RabbitSend) -> BatchResult:
    """Publish outbox rows (ordered by id).

    Kafka rows are produced together then flushed (kafka_send returns {row_id: error} for failures).
    Ordering rule: once a Kafka row for a key fails, every later row with the same key in this batch is held
    back (left unsent, so it is re-published later — consumers are version-checked, so a resend is harmless)
    and consumers never miss an older version that a newer one would mask.
    RabbitMQ commands carry no ordering guarantee; each is confirmed individually.
    """
    result = BatchResult()
    kafka_rows = [r for r in rows if r["destination"] == "kafka"]
    if kafka_rows:
        failures = kafka_send(kafka_rows)
        blocked: set[tuple[str, str | None]] = set()
        for r in kafka_rows:
            k = (r["topic_or_queue"], r["msg_key"])
            if k in blocked:
                continue
            if r["id"] in failures:
                result.failed[r["id"]] = failures[r["id"]]
                blocked.add(k)
            else:
                result.sent.append(r["id"])
    for r in rows:
        if r["destination"] != "rabbitmq":
            continue
        try:
            rabbit_send(r)
            result.sent.append(r["id"])
        except Exception as exc:  # noqa: BLE001
            result.failed[r["id"]] = str(exc)[:500]
    return result
