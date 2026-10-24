"""Redis key builders and Lua scripts (docs/CONTRACTS.md §7)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

IDEM_TTL_S = 24 * 3600
STOCK_TTL_S = 600
FILL_LOCK_TTL_S = 2
LEASE_TTL_S = 300
REORDER_TTL_S = 24 * 3600
SETTING_TTL_S = 60
STATION_RATE_LIMIT_PER_S = 200

REVIEW_READY = "review:ready"


def idem_capture(capture_id: str) -> str:
    return f"idem:capture:{capture_id}"


def stock(sku: str) -> str:
    return f"stock:{sku}"


def fill_lock(sku: str) -> str:
    return f"lock:fill:{sku}"


def review_lease(task_id: str) -> str:
    return f"review:lease:{task_id}"


def reorder_sent(sku: str, day: datetime | None = None) -> str:
    d = (day or datetime.now(UTC)).strftime("%Y%m%d")
    return f"reorder:sent:{sku}:{d}"


def rate_limit(station_id: str, epoch_s: int) -> str:
    return f"rl:{station_id}:{epoch_s}"


def setting(key: str) -> str:
    return f"setting:{key}"


def review_score(priority: int, created_at: datetime) -> float:
    """Lower pops first: priority dominates, then age (older first)."""
    return priority * 1e10 + created_at.timestamp()


# KEYS[1] = stock:{sku}; ARGV = ttl, mode ('fill' | 'update'), then (location_id, on_hand, version) triples.
# Writes each location only when its version is newer than the cached one.
# 'update' (cache-updater) only touches hashes that a full 'fill' has populated (marked by `_filled`), so a
# cold key never holds a partial set of locations; returns -1 in that case. Otherwise returns #applied.
STOCK_WRITE_LUA = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local mode = ARGV[2]
if mode == 'update' and redis.call('HEXISTS', key, '_filled') == 0 then
  return -1
end
local applied = 0
for i = 3, #ARGV, 3 do
  local loc = ARGV[i]
  local on_hand = ARGV[i + 1]
  local ver = tonumber(ARGV[i + 2])
  local cur = tonumber(redis.call('HGET', key, '_v:' .. loc) or '-1')
  if ver > cur then
    redis.call('HSET', key, loc, on_hand, '_v:' .. loc, ver)
    applied = applied + 1
  end
end
if mode == 'fill' then
  redis.call('HSET', key, '_filled', '1')
end
redis.call('EXPIRE', key, ttl)
return applied
"""


def parse_stock_hash(h: dict[str, str]) -> list[dict[str, Any]] | None:
    """Turn a `stock:{sku}` hash into [{location_id, on_hand, version}] sorted by location.
    Returns None when the hash is not a complete fill (cache miss)."""
    if h.get("_filled") != "1":
        return None
    out: list[dict[str, Any]] = []
    for field, val in h.items():
        if field.startswith("_"):
            continue
        out.append({"location_id": field, "on_hand": int(val), "version": int(h.get(f"_v:{field}", 0))})
    return sorted(out, key=lambda r: str(r["location_id"]))
