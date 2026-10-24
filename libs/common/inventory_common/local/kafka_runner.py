"""Emulates a Lambda MSK event-source mapping against a real Kafka broker.

    python -m inventory_common.local.kafka_runner --topic captures.raw --group extract \
        --handler extract.handler.handler --batch-size 100 --max-wait-ms 500

Semantics match the ESM closely enough for local testing: batches are grouped per partition,
offsets are committed only after the handler returns, and a failed batch is retried from the first
uncommitted offset (at-least-once).
"""

from __future__ import annotations

import argparse
import base64
import importlib
import signal
import time
from collections import defaultdict
from typing import Any

from confluent_kafka import Consumer, KafkaException, TopicPartition

from inventory_common.kafka import base_config
from inventory_common.log import get_logger

log = get_logger("kafka_runner")


def load_handler(path: str) -> Any:
    mod, _, fn = path.rpartition(".")
    return getattr(importlib.import_module(mod), fn)


def to_event(msgs: list[Any]) -> dict[str, Any]:
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in msgs:
        ts_type, ts = m.timestamp()
        records[f"{m.topic()}-{m.partition()}"].append(
            {
                "topic": m.topic(),
                "partition": m.partition(),
                "offset": m.offset(),
                "timestamp": ts,
                "timestampType": "CREATE_TIME" if ts_type == 1 else "LOG_APPEND_TIME",
                "key": base64.b64encode(m.key()).decode() if m.key() else None,
                "value": base64.b64encode(m.value() or b"").decode(),
                "headers": [{k: list(v or b"")} for k, v in (m.headers() or [])],
            }
        )
    return {"eventSource": "aws:kafka", "eventSourceArn": "local", "records": dict(records)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--group", required=True)
    ap.add_argument("--handler", required=True)
    ap.add_argument("--batch-size", type=int, default=100)
    ap.add_argument("--max-wait-ms", type=int, default=500)
    args = ap.parse_args()

    handler = load_handler(args.handler)
    conf = base_config()
    conf.update(
        {
            "group.id": args.group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "max.poll.interval.ms": 900000,
        }
    )
    consumer = Consumer(conf)
    consumer.subscribe([args.topic])
    running = True

    def stop(*_: Any) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("kafka runner started", extra={"topic": args.topic, "group": args.group, "handler": args.handler})

    backoff = 1.0
    while running:
        msgs = consumer.consume(num_messages=args.batch_size, timeout=args.max_wait_ms / 1000)
        msgs = [m for m in msgs if m.error() is None]
        if not msgs:
            continue
        try:
            handler(to_event(msgs), None)
            offsets: dict[tuple[str, int], int] = {}
            for m in msgs:
                tp = (str(m.topic()), int(m.partition() or 0))
                offsets[tp] = max(offsets.get(tp, -1), int(m.offset() or 0))
            consumer.commit(
                offsets=[TopicPartition(t, p, o + 1) for (t, p), o in offsets.items()], asynchronous=False
            )
            backoff = 1.0
        except (Exception, KafkaException):  # noqa: BLE001
            log.exception("handler failed; rewinding batch", extra={"size": len(msgs)})
            firsts: dict[tuple[str, int], int] = {}
            for m in msgs:
                firsts.setdefault((str(m.topic()), int(m.partition() or 0)), int(m.offset() or 0))
            for (t, p), o in firsts.items():
                consumer.seek(TopicPartition(t, p, o))
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
    consumer.close()


if __name__ == "__main__":
    main()
