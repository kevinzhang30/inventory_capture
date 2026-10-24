"""Redrive tooling for poison messages.

    python -m ops.redrive rabbit --queue review.dispatch [--limit 100] [--dry-run]
        Moves messages from <queue>.dlq back to the `commands` exchange (x-attempt reset).
    python -m ops.redrive kafka-dlq [--queue-url $KAFKA_DLQ_URL] [--limit 10]
        Prints failed-batch descriptors from the Lambda on-failure SQS destination (topic/partition/offsets),
        which can be replayed by re-running the consumer from those offsets.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from inventory_common import rabbit


def redrive_rabbit(queue: str, limit: int, dry_run: bool) -> dict[str, int]:
    if queue not in rabbit.QUEUES:
        raise SystemExit(f"unknown queue {queue}; valid: {rabbit.QUEUES}")
    conn = rabbit.connect()
    ch = conn.channel()
    ch.confirm_delivery()
    moved = 0
    try:
        while moved < limit:
            method, props, body = ch.basic_get(f"{queue}.dlq", auto_ack=False)
            if method is None:
                break
            if dry_run:
                print(json.dumps({"headers": props.headers, "body": body.decode("utf-8", "replace")[:500]}))
                ch.basic_nack(method.delivery_tag, requeue=True)
                moved += 1
                continue
            headers = {k: v for k, v in (props.headers or {}).items() if k not in ("x-attempt", "x-last-error")}
            headers["x-redriven"] = 1
            ch.basic_publish(rabbit.EXCHANGE, queue, body, props.__class__(
                content_type=props.content_type, delivery_mode=2, message_id=props.message_id, headers=headers))
            ch.basic_ack(method.delivery_tag)
            moved += 1
    finally:
        conn.close()
    return {"moved" if not dry_run else "inspected": moved}


def kafka_dlq(queue_url: str, limit: int) -> list[dict[str, Any]]:
    import boto3

    sqs = boto3.client("sqs")
    out = []
    resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=min(limit, 10), WaitTimeSeconds=2,
                               VisibilityTimeout=30)
    for m in resp.get("Messages", []):
        body = json.loads(m["Body"])
        info = body.get("KafkaBatchInfo") or body.get("requestContext") or body
        out.append({"message_id": m["MessageId"], "batch": info})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rabbit")
    r.add_argument("--queue", required=True)
    r.add_argument("--limit", type=int, default=100)
    r.add_argument("--dry-run", action="store_true")
    k = sub.add_parser("kafka-dlq")
    k.add_argument("--queue-url", default=os.environ.get("KAFKA_DLQ_URL"))
    k.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    if args.cmd == "rabbit":
        print(redrive_rabbit(args.queue, args.limit, args.dry_run))
    else:
        if not args.queue_url:
            raise SystemExit("--queue-url or KAFKA_DLQ_URL required")
        for item in kafka_dlq(args.queue_url, args.limit):
            print(json.dumps(item, default=str))


if __name__ == "__main__":
    main()
