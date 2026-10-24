"""RabbitMQ publishing and topology (docs/CONTRACTS.md §5)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel

from inventory_common.config import rabbitmq_url, settings
from inventory_common.log import get_logger

log = get_logger(__name__)

EXCHANGE = "commands"
RETRY_EXCHANGE = "commands.retry"
DLQ_EXCHANGE = "commands.dlq"
QUEUES = ("review.dispatch", "reorder.request", "notify")
RETRY_TTL_MS = 15000
MAX_ATTEMPTS = 5

_conn: pika.BlockingConnection | None = None
_chan: BlockingChannel | None = None


def connect() -> pika.BlockingConnection:
    params = pika.URLParameters(rabbitmq_url())
    params.heartbeat = 30
    params.blocked_connection_timeout = 30
    return pika.BlockingConnection(params)


def get_channel() -> BlockingChannel:
    global _conn, _chan
    if _conn is None or _conn.is_closed or _chan is None or _chan.is_closed:
        _conn = connect()
        _chan = _conn.channel()
        _chan.confirm_delivery()
    return _chan


def reset() -> None:
    global _conn, _chan
    try:
        if _conn is not None and _conn.is_open:
            _conn.close()
    except Exception:  # noqa: BLE001
        pass
    _conn, _chan = None, None


def declare_topology(ch: BlockingChannel | None = None) -> None:
    """Idempotently declare exchanges and queues. Safe to call on every start."""
    ch = ch or get_channel()
    for ex in (EXCHANGE, RETRY_EXCHANGE, DLQ_EXCHANGE):
        ch.exchange_declare(exchange=ex, exchange_type="direct", durable=True)
    for q in QUEUES:
        ch.queue_declare(queue=q, durable=True, arguments={"x-queue-type": settings.rabbitmq_queue_type})
        ch.queue_bind(queue=q, exchange=EXCHANGE, routing_key=q)
        ch.queue_declare(
            queue=f"{q}.retry",
            durable=True,
            arguments={
                "x-queue-type": "classic",
                "x-message-ttl": RETRY_TTL_MS,
                "x-dead-letter-exchange": EXCHANGE,
                "x-dead-letter-routing-key": q,
            },
        )
        ch.queue_bind(queue=f"{q}.retry", exchange=RETRY_EXCHANGE, routing_key=q)
        ch.queue_declare(
            queue=f"{q}.dlq", durable=True, arguments={"x-queue-type": settings.rabbitmq_queue_type}
        )
        ch.queue_bind(queue=f"{q}.dlq", exchange=DLQ_EXCHANGE, routing_key=q)
    log.info("rabbitmq topology declared", extra={"queues": list(QUEUES)})


def publish(
    queue: str,
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
    exchange: str = EXCHANGE,
    message_id: str | None = None,
) -> None:
    """Publish with publisher confirms. Raises on failure (caller decides whether to retry)."""
    body = json.dumps(payload, default=str).encode()
    props = pika.BasicProperties(
        content_type="application/json",
        delivery_mode=2,
        message_id=message_id or str(payload.get("command_id") or uuid.uuid4()),
        headers=headers or {},
    )
    for attempt in (1, 2):
        try:
            get_channel().basic_publish(
                exchange=exchange, routing_key=queue, body=body, properties=props, mandatory=True
            )
            return
        except (pika.exceptions.AMQPConnectionError, pika.exceptions.ChannelClosed,
                pika.exceptions.StreamLostError):
            reset()
            if attempt == 2:
                raise
