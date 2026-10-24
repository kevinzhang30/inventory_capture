import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

import fakeredis
import pytest

from inventory_common import keys, redis_client
from review_dispatcher import handler as dispatcher
from review_dispatcher import notify, reaper

NOW = datetime(2026, 10, 22, tzinfo=UTC)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def fake_db(monkeypatch, module, fn):
    class Conn:
        def execute(self, sql, params=None):
            return Result(fn(sql, params))

        def rollback(self):
            pass

    @contextmanager
    def cm():
        yield Conn()

    for name in ("connection", "transaction"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, cm)


@pytest.fixture()
def r(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_client", client)
    monkeypatch.setattr(reaper, "emit_metric", lambda *a, **k: None)
    return client


def cmd():
    return {"command_id": "c", "extraction_id": str(uuid.uuid4()), "capture_id": str(uuid.uuid4()),
            "reason": "low_confidence", "priority": 4, "min_confidence": 0.5}


def test_dispatch_enqueues_ready_task_idempotently(r, monkeypatch):
    fake_db(monkeypatch, dispatcher,
            lambda sql, p: [{"task_id": "t1", "status": "ready", "priority": 4, "created_at": NOW}])
    payload = cmd()
    assert dispatcher.dispatch(payload) == "t1"
    assert dispatcher.dispatch(payload) == "t1"
    assert r.zrange(keys.REVIEW_READY, 0, -1, withscores=True) == [("t1", keys.review_score(4, NOW))]


def test_dispatch_skips_done_task(r, monkeypatch):
    fake_db(monkeypatch, dispatcher, lambda sql, p: [{"task_id": "t1", "status": "done", "priority": 4,
                                                       "created_at": NOW}])
    assert dispatcher.dispatch(cmd()) is None
    assert r.zcard(keys.REVIEW_READY) == 0


def test_reaper_requeues_only_tasks_without_lease(r, monkeypatch):
    r.set(keys.review_lease("live"), "alice")

    def db(sql, p):
        if "WHERE status = 'claimed' AND lease_expires_at < now() LIMIT" in sql:
            return [{"task_id": "live"}, {"task_id": "dead"}]
        if "UPDATE review_task" in sql:
            assert p[0] == ["dead"]
            return [{"task_id": "dead", "priority": 2, "created_at": NOW}]
        return []

    fake_db(monkeypatch, reaper, db)
    assert reaper.requeue_expired() == 1
    assert r.zrange(keys.REVIEW_READY, 0, -1) == ["dead"]


def test_reconcile_pages(r, monkeypatch):
    monkeypatch.setattr(reaper, "PAGE", 2)
    ready = [{"task_id": f"0000000{i}", "priority": 1, "created_at": NOW} for i in range(3)]
    r.zadd(keys.REVIEW_READY, {"00000000": 1.0})

    def db(sql, p):
        last, page = p
        return [t for t in ready if t["task_id"] > last.replace("-", "")[:8]][:page] if last != ready[-1]["task_id"] \
            else []

    fake_db(monkeypatch, reaper, db)
    assert reaper.reconcile_ready() == 2
    assert r.zcard(keys.REVIEW_READY) == 3


def test_notify_dedupes(r, monkeypatch):
    sent = []
    monkeypatch.setattr(notify.log, "info", lambda *a, **k: sent.append(a))
    payload = {"command_id": "n1", "channel": "log", "subject": "s", "message": "m"}
    assert notify.send(payload) is True
    assert notify.send(payload) is False
    assert len(sent) == 1
