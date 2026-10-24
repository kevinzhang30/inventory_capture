"""Kafka producer/consumer config. KAFKA_AUTH=iam targets MSK Serverless with IAM (OAUTHBEARER)."""

from __future__ import annotations

import json
from typing import Any

from confluent_kafka import Producer

from inventory_common.config import settings
from inventory_common.log import get_logger

log = get_logger(__name__)
_producer: Producer | None = None


def _oauth_cb(_oauth_config: Any) -> tuple[str, float]:
    from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

    token, expiry_ms = MSKAuthTokenProvider.generate_auth_token(settings.aws_region)
    return token, expiry_ms / 1000


def base_config() -> dict[str, Any]:
    conf: dict[str, Any] = {"bootstrap.servers": settings.kafka_bootstrap}
    if settings.kafka_auth == "iam":
        conf.update(
            {
                "security.protocol": "SASL_SSL",
                "sasl.mechanism": "OAUTHBEARER",
                "oauth_cb": _oauth_cb,
            }
        )
    return conf


def get_producer() -> Producer:
    global _producer
    if _producer is None:
        conf = base_config()
        conf.update(
            {
                "acks": "all",
                "enable.idempotence": True,
                "linger.ms": 5,
                "compression.type": "lz4",
                "message.timeout.ms": 30000,
            }
        )
        _producer = Producer(conf)
        _producer.poll(0)  # triggers oauth_cb so the first produce does not stall
    return _producer


class DeliveryTracker:
    """Collects per-message delivery results so callers can report partial failure."""

    def __init__(self) -> None:
        self.failed: dict[str, str] = {}
        self.delivered: set[str] = set()

    def callback(self, ref: str) -> Any:
        def _cb(err: Any, _msg: Any) -> None:
            if err is not None:
                self.failed[ref] = str(err)
            else:
                self.delivered.add(ref)

        return _cb


def produce_json(
    topic: str,
    key: str | None,
    value: dict[str, Any],
    headers: dict[str, str] | None = None,
    on_delivery: Any = None,
) -> None:
    p = get_producer()
    data = json.dumps(value, default=str).encode()
    hdrs: list[tuple[str, str | bytes | None]] = [(k, v.encode()) for k, v in (headers or {}).items()]
    while True:
        try:
            p.produce(
                topic, key=key.encode() if key else None, value=data, headers=hdrs, on_delivery=on_delivery
            )
            break
        except BufferError:
            p.poll(0.05)
    p.poll(0)


def flush(timeout: float = 10.0) -> int:
    """Flush the producer; returns number of messages still in queue."""
    if _producer is None:
        return 0
    return _producer.flush(timeout)
