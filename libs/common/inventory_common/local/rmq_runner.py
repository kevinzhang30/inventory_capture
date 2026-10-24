"""Emulates a Lambda Amazon MQ (RabbitMQ) event-source mapping against a real broker.

    python -m inventory_common.local.rmq_runner --queue review.dispatch \
        --handler review_dispatcher.handler.handler --batch-size 10
"""

from __future__ import annotations

import argparse
import base64
import time
from typing import Any

from inventory_common import rabbit
from inventory_common.local.kafka_runner import load_handler
from inventory_common.log import get_logger

log = get_logger("rmq_runner")


def _hdr(v: Any) -> Any:
    if isinstance(v, bytes):
        return {"bytes": list(v)}
    if isinstance(v, str):
        return {"bytes": list(v.encode())}
    return v


def to_event(queue: str, batch: list[tuple[Any, Any, bytes]]) -> dict[str, Any]:
    msgs = []
    for method, props, body in batch:
        msgs.append(
            {
                "basicProperties": {
                    "contentType": props.content_type,
                    "deliveryMode": props.delivery_mode,
                    "messageId": props.message_id,
                    "headers": {k: _hdr(v) for k, v in (props.headers or {}).items()},
                },
                "redelivered": bool(method.redelivered),
                "data": base64.b64encode(body).decode(),
            }
        )
    return {"eventSource": "aws:rmq", "eventSourceArn": "local", "rmqMessagesByQueue": {f"{queue}::/": msgs}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", required=True)
    ap.add_argument("--handler", required=True)
    ap.add_argument("--batch-size", type=int, default=10)
    ap.add_argument("--max-wait-ms", type=int, default=500)
    args = ap.parse_args()
    handler = load_handler(args.handler)

    while True:
        try:
            conn = rabbit.connect()
            ch = conn.channel()
            rabbit.declare_topology(ch)
            ch.basic_qos(prefetch_count=args.batch_size)
            log.info("rmq runner started", extra={"queue": args.queue, "handler": args.handler})
            while True:
                batch: list[tuple[Any, Any, bytes]] = []
                deadline = time.monotonic() + args.max_wait_ms / 1000
                while len(batch) < args.batch_size and time.monotonic() < deadline:
                    method, props, body = ch.basic_get(args.queue, auto_ack=False)
                    if method is None:
                        conn.sleep(0.05)
                        continue
                    batch.append((method, props, body))
                if not batch:
                    continue
                try:
                    handler(to_event(args.queue, batch), None)
                    ch.basic_ack(batch[-1][0].delivery_tag, multiple=True)
                except Exception:  # noqa: BLE001
                    log.exception("handler failed; requeueing batch")
                    ch.basic_nack(batch[-1][0].delivery_tag, multiple=True, requeue=True)
                    conn.sleep(1)
        except Exception:  # noqa: BLE001
            log.exception("rmq connection lost; reconnecting")
            time.sleep(2)


if __name__ == "__main__":
    main()
