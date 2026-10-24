"""notify worker (Amazon MQ notify): SNS publish or structured log, deduplicated per command."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from inventory_common.config import settings
from inventory_common.lambda_events import RmqMessage, rmq_consume
from inventory_common.log import get_logger
from inventory_common.models import Notify
from inventory_common.redis_client import get_redis

log = get_logger(__name__)
DEDUPE_TTL_S = 24 * 3600


@lru_cache(maxsize=1)
def _sns() -> Any:
    import boto3

    return boto3.client("sns", region_name=settings.aws_region)


def send(payload: dict[str, Any], _msg: RmqMessage | None = None) -> bool:
    n = Notify.model_validate(payload)
    r = get_redis()
    key = f"notify:sent:{n.command_id}"
    if not r.set(key, "1", nx=True, ex=DEDUPE_TTL_S):
        return False
    try:
        if n.channel == "sns" and settings.sns_topic_arn:
            _sns().publish(TopicArn=settings.sns_topic_arn, Subject=n.subject[:100], Message=n.message)
        else:
            log.info("notification", extra={"subject": n.subject, "body": n.message})
    except Exception:
        r.delete(key)
        raise
    return True


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    return rmq_consume(event, send)
