"""Redis / Valkey client. Uses RedisCluster against ElastiCache Serverless (REDIS_CLUSTER=true)."""

from __future__ import annotations

from typing import Any

import redis
from redis.cluster import RedisCluster

from inventory_common import keys
from inventory_common.config import settings

_client: Any = None
_stock_script: Any = None


def get_redis() -> Any:
    global _client
    if _client is None:
        if settings.redis_cluster:
            _client = RedisCluster.from_url(settings.redis_url, decode_responses=True)
        else:
            _client = redis.Redis.from_url(
                settings.redis_url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2
            )
    return _client


def write_stock(sku: str, rows: list[tuple[str, int, int]], fill: bool = False) -> int:
    """Version-checked write of [(location_id, on_hand, version)] into stock:{sku}.

    fill=True: complete snapshot from Postgres (core-api cache miss); rows may be empty for a SKU with no stock.
    fill=False: incremental update from cache-updater; skipped (returns -1) when the key is not filled."""
    global _stock_script
    if not rows and not fill:
        return 0
    r = get_redis()
    if _stock_script is None:
        _stock_script = r.register_script(keys.STOCK_WRITE_LUA)
    args: list[Any] = [keys.STOCK_TTL_S, "fill" if fill else "update"]
    for loc, on_hand, ver in rows:
        args += [loc, on_hand, ver]
    return int(_stock_script(keys=[keys.stock(sku)], args=args))
