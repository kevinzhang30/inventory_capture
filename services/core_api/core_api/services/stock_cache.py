"""Stock read path (design §6.5): Redis first; on miss a single-flight fill from Postgres."""

from __future__ import annotations

import time
import uuid
from typing import Any

import redis

from core_api.errors import ApiError
from inventory_common import keys
from inventory_common.db import connection
from inventory_common.log import get_logger
from inventory_common.redis_client import get_redis, write_stock

log = get_logger(__name__)

WAIT_STEP_S = 0.025
WAIT_TOTAL_S = 0.4
RELEASE_LUA = "if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) else return 0 end"


def _payload(sku: str, rows: list[dict[str, Any]], source: str) -> dict[str, Any]:
    return {"sku": sku, "on_hand_total": sum(int(r["on_hand"]) for r in rows), "locations": rows, "source": source}


def load_from_db(sku: str) -> list[dict[str, Any]]:
    with connection() as conn:
        if conn.execute("SELECT 1 FROM part WHERE sku = %s", (sku,)).fetchone() is None:
            conn.rollback()
            raise ApiError(404, "not_found", f"unknown sku {sku}")
        rows = conn.execute(
            "SELECT location_id, on_hand, version FROM stock_level WHERE sku = %s ORDER BY location_id", (sku,)
        ).fetchall()
        conn.rollback()
    return [{"location_id": r["location_id"], "on_hand": r["on_hand"], "version": r["version"]} for r in rows]


def get_stock(sku: str) -> dict[str, Any]:
    try:
        r = get_redis()
        rows = keys.parse_stock_hash(r.hgetall(keys.stock(sku)))
        if rows is not None:
            return _payload(sku, rows, "cache")
        token = uuid.uuid4().hex
        if r.set(keys.fill_lock(sku), token, nx=True, px=keys.FILL_LOCK_TTL_S * 1000):
            try:
                rows = load_from_db(sku)
                write_stock(sku, [(x["location_id"], x["on_hand"], x["version"]) for x in rows], fill=True)
                return _payload(sku, rows, "db")
            finally:
                r.eval(RELEASE_LUA, 1, keys.fill_lock(sku), token)
        deadline = time.monotonic() + WAIT_TOTAL_S
        while time.monotonic() < deadline:
            time.sleep(WAIT_STEP_S)
            rows = keys.parse_stock_hash(r.hgetall(keys.stock(sku)))
            if rows is not None:
                return _payload(sku, rows, "cache")
    except redis.RedisError:
        log.warning("redis unavailable; serving stock from postgres", extra={"sku": sku})
    return _payload(sku, load_from_db(sku), "db")
