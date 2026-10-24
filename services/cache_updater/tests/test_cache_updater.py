import base64
import json

import fakeredis
import pytest

from cache_updater import handler as cu
from inventory_common import keys, redis_client


@pytest.fixture()
def r(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_client", client)
    monkeypatch.setattr(redis_client, "_stock_script", None)
    monkeypatch.setattr(cu, "emit_metric", lambda *a, **k: None)
    return client


def ev(*events):
    return {"records": {"inventory.events-0": [
        {"topic": "inventory.events", "partition": 0, "offset": i, "key": None,
         "value": base64.b64encode(json.dumps(e).encode()).decode()} for i, e in enumerate(events)]}}


def sc(sku, loc, on_hand, ver):
    return {"type": "stock.changed", "sku": sku, "location_id": loc, "on_hand": on_hand, "version": ver,
            "captured_at": "2026-10-22T10:00:00+00:00"}


def test_latest_per_location():
    out = cu.latest_per_location([sc("A", "L1", 1, 1), sc("A", "L1", 3, 3), sc("A", "L1", 2, 2), sc("B", "L1", 9, 1)])
    assert out == {"A": [("L1", 3, 3)], "B": [("L1", 9, 1)]}


def test_updates_filled_keys_and_skips_cold(r):
    redis_client.write_stock("A", [("L1", 0, 0)], fill=True)
    res = cu.handler(ev(sc("A", "L1", 5, 1), sc("A", "L1", 7, 2), sc("B", "L1", 1, 1), {"type": "part.upserted"}), None)
    assert res == {"events": 3, "applied": 1, "cold_skus": 1}
    assert keys.parse_stock_hash(r.hgetall("stock:A")) == [{"location_id": "L1", "on_hand": 7, "version": 2}]
    assert not r.exists("stock:B")
