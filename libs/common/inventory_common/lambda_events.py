"""Decoders for Lambda MSK and Amazon MQ (RabbitMQ) event shapes, plus the RabbitMQ retry/DLQ consumer."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from inventory_common import rabbit
from inventory_common.log import get_logger

log = get_logger(__name__)


@dataclass
class KafkaRecord:
    topic: str
    partition: int
    offset: int
    timestamp: int
    key: str | None
    value: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.value)


def _bytes_to_str(v: Any) -> str:
    if isinstance(v, dict) and "bytes" in v:
        v = v["bytes"]
    if isinstance(v, list):
        return bytes(v).decode("utf-8", "replace")
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return str(v)


def iter_kafka_records(event: dict[str, Any]) -> Iterator[KafkaRecord]:
    """Yield records in partition order (ordering is preserved within each partition list)."""
    for records in (event.get("records") or {}).values():
        for r in records:
            headers: dict[str, str] = {}
            for h in r.get("headers") or []:
                for k, v in h.items():
                    headers[k] = _bytes_to_str(v)
            yield KafkaRecord(
                topic=r["topic"],
                partition=int(r["partition"]),
                offset=int(r["offset"]),
                timestamp=int(r.get("timestamp") or 0),
                key=base64.b64decode(r["key"]).decode() if r.get("key") else None,
                value=base64.b64decode(r["value"]) if r.get("value") else b"null",
                headers=headers,
            )


@dataclass
class RmqMessage:
    queue: str
    data: bytes
    headers: dict[str, Any]
    redelivered: bool
    message_id: str | None

    def json(self) -> Any:
        return json.loads(self.data)


def _decode_header(v: Any) -> Any:
    if isinstance(v, dict) and "bytes" in v:
        return _bytes_to_str(v)
    if isinstance(v, list) and v and all(isinstance(x, int) for x in v):
        return _bytes_to_str(v)
    return v


def iter_rmq_messages(event: dict[str, Any]) -> Iterator[RmqMessage]:
    for qkey, msgs in (event.get("rmqMessagesByQueue") or {}).items():
        queue = qkey.split("::", 1)[0]
        for m in msgs:
            props = m.get("basicProperties") or {}
            headers = {k: _decode_header(v) for k, v in (props.get("headers") or {}).items()}
            yield RmqMessage(
                queue=queue,
                data=base64.b64decode(m.get("data") or ""),
                headers=headers,
                redelivered=bool(m.get("redelivered")),
                message_id=props.get("messageId"),
            )


def rmq_consume(event: dict[str, Any], fn: Callable[[dict[str, Any], RmqMessage], Any]) -> dict[str, int]:
    """Process each message; failures are re-published to <queue>.retry (TTL) or <queue>.dlq after
    MAX_ATTEMPTS. The batch itself always succeeds so one poison message cannot block the queue.
    If the retry publish itself fails we raise, and Lambda redelivers the batch (handlers are idempotent)."""
    stats = {"ok": 0, "retried": 0, "dead_lettered": 0}
    for msg in iter_rmq_messages(event):
        try:
            payload = msg.json()
            fn(payload, msg)
            stats["ok"] += 1
        except Exception as exc:  # noqa: BLE001
            attempt = int(msg.headers.get("x-attempt") or 0) + 1
            headers = {**msg.headers, "x-attempt": attempt, "x-last-error": str(exc)[:500]}
            if attempt >= rabbit.MAX_ATTEMPTS:
                rabbit.publish(msg.queue, _safe_json(msg.data), headers, exchange=rabbit.DLQ_EXCHANGE,
                               message_id=msg.message_id)
                stats["dead_lettered"] += 1
                log.error("message dead-lettered", extra={"queue": msg.queue, "attempt": attempt},
                          exc_info=True)
            else:
                rabbit.publish(msg.queue, _safe_json(msg.data), headers, exchange=rabbit.RETRY_EXCHANGE,
                               message_id=msg.message_id)
                stats["retried"] += 1
                log.warning("message scheduled for retry", extra={"queue": msg.queue, "attempt": attempt},
                            exc_info=True)
    return stats


def _safe_json(data: bytes) -> Any:
    try:
        return json.loads(data)
    except ValueError:
        return {"_raw": data.decode("utf-8", "replace")}
