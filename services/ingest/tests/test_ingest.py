import json
import uuid

import fakeredis
import pytest

from ingest import handler as ingest
from inventory_common import keys, redis_client


class FakeProducer:
    def __init__(self, fail: set[str] | None = None):
        self.sent: list[tuple[str, dict]] = []
        self.fail = fail or set()
        self.callbacks = []

    def produce(self, topic, key, value, headers=None, on_delivery=None):
        self.sent.append((key, value))
        self.callbacks.append((key, on_delivery))


@pytest.fixture()
def env(monkeypatch):
    r = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_client", r)
    monkeypatch.setattr(ingest.settings, "auth_mode", "dev")
    prod = FakeProducer()

    def produce_json(topic, key, value, headers, on_delivery):
        prod.sent.append((key, value))
        on_delivery(Exception("broker down") if key in prod.fail else None, None)

    monkeypatch.setattr(ingest, "produce_json", produce_json)
    monkeypatch.setattr(ingest, "flush", lambda t: 0)
    monkeypatch.setattr(ingest, "emit_metric", lambda *a, **k: None)
    return r, prod


def scan(cid=None, station="S1", qty=1):
    return {"capture_id": cid or str(uuid.uuid4()), "site_id": "DAL1", "station_id": station, "kind": "scan",
            "captured_at": "2026-10-22T10:00:00Z", "payload": {"sku": "SKU-000001", "qty": qty,
                                                                "location_id": "DAL1-A01-01"}}


def call(body, groups="operator"):
    ev = {"rawPath": "/captures", "requestContext": {"http": {"method": "POST"}},
          "headers": {"x-dev-user": "op-1", "x-dev-groups": groups}, "body": json.dumps(body)}
    res = ingest.handler(ev, None)
    return res["statusCode"], json.loads(res["body"])


def test_accepts_and_dedupes(env):
    _, prod = env
    c = scan()
    status, body = call({"captures": [c]})
    assert status == 202 and body["results"][0]["status"] == "accepted"
    assert prod.sent[0][1]["operator_id"] == "op-1"
    _, body = call({"captures": [c]})
    assert body["results"][0]["status"] == "duplicate"
    assert len(prod.sent) == 1


def test_partial_rejection(env):
    status, body = call({"captures": [scan(), scan(qty=0), {"capture_id": "x"}]})
    assert status == 202
    assert [r["status"] for r in body["results"]] == ["accepted", "rejected", "rejected"]


def test_produce_failure_releases_idempotency_key(env):
    r, prod = env
    c = scan()
    prod.fail.add(c["capture_id"])
    _, body = call({"captures": [c]})
    assert body["results"][0] == {"capture_id": c["capture_id"], "status": "rejected", "error": "produce_failed"}
    assert r.get(keys.idem_capture(c["capture_id"])) is None


def test_rate_limit(env, monkeypatch):
    monkeypatch.setattr(keys, "STATION_RATE_LIMIT_PER_S", 2)
    _, body = call({"captures": [scan() for _ in range(3)]})
    assert [r["status"] for r in body["results"]] == ["accepted", "accepted", "rejected"]
    assert body["results"][2]["error"] == "rate_limited"


def test_role_and_batch_validation(env):
    assert call({"captures": [scan()]}, groups="reviewer")[0] == 403
    assert call({"captures": []})[0] == 400
    assert call({"captures": [scan() for _ in range(51)]})[0] == 400


def test_upload_presign(env, monkeypatch):
    monkeypatch.setattr(ingest.s3, "presign_put", lambda key, ct, exp: f"https://s3/{key}")
    cid = str(uuid.uuid4())
    ev = {"rawPath": "/uploads", "requestContext": {"http": {"method": "POST"}}, "headers": {},
          "body": json.dumps({"capture_id": cid, "content_type": "image/png"})}
    res = ingest.handler(ev, None)
    body = json.loads(res["body"])
    assert res["statusCode"] == 200 and body["s3_key"].endswith(f"{cid}.png")
    ev["body"] = json.dumps({"capture_id": cid, "content_type": "text/html"})
    assert ingest.handler(ev, None)["statusCode"] == 400
