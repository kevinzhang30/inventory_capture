"""Runtime-tunable settings stored in `app_setting`, cached in Redis and in-process for 60 s."""

from __future__ import annotations

import json
import time
from typing import Any

from inventory_common import keys
from inventory_common.config import settings
from inventory_common.db import connection
from inventory_common.log import get_logger
from inventory_common.redis_client import get_redis

log = get_logger(__name__)
_local: dict[str, tuple[float, Any]] = {}


def get_setting(key: str, default: Any = None) -> Any:
    hit = _local.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value: Any = None
    try:
        cached = get_redis().get(keys.setting(key))
        if cached is not None:
            value = json.loads(cached)
    except Exception:  # noqa: BLE001 - cache is an optimisation
        log.warning("setting cache read failed", extra={"key": key})
    if value is None:
        with connection() as conn:
            row = conn.execute("SELECT value FROM app_setting WHERE key = %s", (key,)).fetchone()
            conn.rollback()
        value = row["value"] if row else None
        try:
            get_redis().set(keys.setting(key), json.dumps(value), ex=keys.SETTING_TTL_S)
        except Exception:  # noqa: BLE001
            pass
    result = default if value is None else value
    _local[key] = (time.monotonic() + keys.SETTING_TTL_S, result)
    return result


def confidence_threshold() -> float:
    return float(get_setting("confidence_threshold", settings.confidence_threshold))


def audit_sample_rate() -> float:
    return float(get_setting("audit_sample_rate", settings.audit_sample_rate))


def invalidate(key: str) -> None:
    _local.pop(key, None)
    try:
        get_redis().delete(keys.setting(key))
    except Exception:  # noqa: BLE001
        pass
