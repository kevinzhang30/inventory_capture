import base64
import json

import fakeredis
import pytest

from inventory_common import redis_client
from reorder_checker import handler as rc


def ev(*events):
    return {"records": {"inventory.events-0": [
        {"topic": "inventory.events", "partition": 0, "offset": i, "key": None,
         "value": base64.b64encode(json.dumps(e).encode()).decode()} for i, e in enumerate(events)]}}


def sc(sku, total, rp):
    return {"type": "stock.changed", "sku": sku, "location_id": "L1", "on_hand": total, "on_hand_total": total,
            "reorder_point": rp, "version": 1}


@pytest.fixture()
def published(monkeypatch):
    monkeypatch.setattr(redis_client, "_client", fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(rc, "emit_metric", lambda *a, **k: None)
    out = []
    monkeypatch.setattr(rc.rabbit, "publish", lambda q, p, message_id=None: out.append((q, p)))
    return out


def test_emits_once_per_day(published):
    assert rc.handler(ev(sc("A", 5, 10), sc("B", 50, 10), sc("C", 0, 0)), None)["reorders"] == 1
    assert rc.handler(ev(sc("A", 4, 10)), None)["reorders"] == 0
    assert published[0][0] == "reorder.request" and published[0][1]["sku"] == "A"


def test_uses_latest_event_per_sku(published):
    assert rc.handler(ev(sc("A", 5, 10), sc("A", 20, 10)), None)["reorders"] == 0


def test_publish_failure_releases_key(monkeypatch, published):
    def boom(*a, **k):
        raise ConnectionError("mq down")

    monkeypatch.setattr(rc.rabbit, "publish", boom)
    with pytest.raises(ConnectionError):
        rc.handler(ev(sc("A", 5, 10)), None)
    monkeypatch.setattr(rc.rabbit, "publish", lambda q, p, message_id=None: published.append((q, p)))
    assert rc.handler(ev(sc("A", 5, 10)), None)["reorders"] == 1
