from contextlib import contextmanager
from datetime import UTC, datetime

import fakeredis
import pytest
import redis
from fastapi.testclient import TestClient

from core_api.app import app
from core_api.errors import ApiError
from core_api.services import reviews, stock_cache
from inventory_common import keys, redis_client
from inventory_common.auth import Principal


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    """Routes SQL to a callback: fn(sql, params) -> list[dict]."""

    def __init__(self, fn):
        self.fn = fn

    def execute(self, sql, params=None):
        return FakeResult(self.fn(sql, params))

    def rollback(self):
        pass


def fake_db(monkeypatch, module, fn):
    @contextmanager
    def cm():
        yield FakeConn(fn)

    for name in ("connection", "transaction"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, cm)


@pytest.fixture()
def r(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_client", client)
    monkeypatch.setattr(redis_client, "_stock_script", None)
    monkeypatch.setattr(reviews, "emit_metric", lambda *a, **k: None)
    return client


# ---------------------------------------------------------------- stock cache

def test_stock_miss_fills_then_hits(r, monkeypatch):
    calls = []
    monkeypatch.setattr(stock_cache, "load_from_db", lambda sku: calls.append(sku) or
                        [{"location_id": "L1", "on_hand": 4, "version": 2}])
    first = stock_cache.get_stock("A")
    second = stock_cache.get_stock("A")
    assert first["source"] == "db" and second["source"] == "cache"
    assert second["on_hand_total"] == 4 and calls == ["A"]
    assert not r.exists(keys.fill_lock("A"))


def test_stock_waits_for_concurrent_fill(r, monkeypatch):
    r.set(keys.fill_lock("A"), "someone-else")
    monkeypatch.setattr(stock_cache, "WAIT_TOTAL_S", 0.05)
    monkeypatch.setattr(stock_cache, "load_from_db", lambda sku: [])
    assert stock_cache.get_stock("A")["source"] == "db"  # gave up waiting, fell back
    redis_client.write_stock("B", [("L1", 1, 1)], fill=True)
    r.set(keys.fill_lock("B"), "someone-else")
    assert stock_cache.get_stock("B")["source"] == "cache"


def test_stock_degrades_when_redis_down(monkeypatch):
    class Broken:
        def hgetall(self, k):
            raise redis.ConnectionError("down")

    monkeypatch.setattr(stock_cache, "get_redis", lambda: Broken())
    monkeypatch.setattr(stock_cache, "load_from_db", lambda sku: [{"location_id": "L", "on_hand": 1, "version": 1}])
    assert stock_cache.get_stock("A")["source"] == "db"


# ---------------------------------------------------------------- reviews

NOW = datetime(2026, 10, 22, tzinfo=UTC)
ALICE = Principal("alice", groups=frozenset({"reviewer"}))
BOB = Principal("bob", groups=frozenset({"reviewer"}))


def test_claim_skips_stale_entries(r, monkeypatch):
    r.zadd(keys.REVIEW_READY, {"stale": keys.review_score(0, NOW), "good": keys.review_score(5, NOW)})

    def db(sql, params):
        if "UPDATE review_task" in sql:
            return [{"task_id": params[2]}] if params[2] == "good" else []
        return []  # "my open task" lookup

    fake_db(monkeypatch, reviews, db)
    monkeypatch.setattr(reviews, "load_task", lambda tid: {"task_id": tid})
    assert reviews.claim_next(ALICE) == {"task_id": "good"}
    assert r.get(keys.review_lease("good")) == "alice"
    assert not r.exists(keys.review_lease("stale"))
    assert reviews.claim_next(ALICE) is None


def test_lease_ownership(r, monkeypatch):
    r.set(keys.review_lease("t1"), "alice", ex=300)
    fake_db(monkeypatch, reviews, lambda sql, params: [{"priority": 3, "created_at": NOW}])
    with pytest.raises(ApiError) as exc:
        reviews.renew("t1", BOB)
    assert exc.value.status == 409 and exc.value.code == "lease_lost"
    assert reviews.renew("t1", ALICE) > NOW
    reviews.release("t1", ALICE)
    assert not r.exists(keys.review_lease("t1"))
    assert r.zscore(keys.REVIEW_READY, "t1") == keys.review_score(3, NOW)


# ---------------------------------------------------------------- HTTP layer

@pytest.fixture()
def client(r, monkeypatch):
    monkeypatch.setattr("inventory_common.auth.settings.auth_mode", "dev")
    return TestClient(app)


def test_health_and_me(client):
    assert client.get("/health").json() == {"status": "ok"}
    me = client.get("/me", headers={"x-dev-user": "u1", "x-dev-groups": "operator"}).json()
    assert me == {"user_id": "u1", "email": "dev@example.com", "groups": ["operator"]}


def test_operator_cannot_claim_reviews(client):
    res = client.post("/reviews/next", headers={"x-dev-groups": "operator"})
    assert res.status_code == 403 and res.json()["error"] == "forbidden"


def test_empty_queue_returns_204(client, monkeypatch):
    monkeypatch.setattr(reviews, "claim_next", lambda p: None)
    assert client.post("/reviews/next", headers={"x-dev-groups": "reviewer"}).status_code == 204


def test_submit_by_non_owner_is_409(client):
    body = {"line_items": [{"line_no": 1, "sku": "A", "qty": 1, "location_id": "L"}]}
    res = client.post("/reviews/t9/submit", json=body, headers={"x-dev-user": "bob", "x-dev-groups": "reviewer"})
    assert res.status_code == 409 and res.json()["error"] == "lease_lost"


def test_validation_error_envelope(client):
    res = client.post("/reviews/t9/submit", json={"nope": 1}, headers={"x-dev-groups": "reviewer"})
    assert res.status_code == 422 and res.json()["error"] == "validation_error"
