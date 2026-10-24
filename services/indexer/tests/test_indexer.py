import json

import pytest

from indexer import handler as ix
from indexer.mappings import ensure_indices


def test_build_operations():
    ops = ix.build_operations([
        {"type": "part.upserted", "sku": "A", "name": "Bolt", "event_id": "x"},
        {"type": "stock.changed", "sku": "A", "location_id": "DAL1-A01-01", "on_hand": 5, "version": 2},
        {"type": "document.extracted", "capture_id": "c1", "occurred_at": "2026-10-22T10:00:00+00:00",
         "line_items": [{"line_no": 1, "sku": "A", "qty": "five"}]},
        {"type": "unknown"},
    ])
    assert len(ops) == 3
    part, stock, doc = ops
    assert part[1]["doc"]["name"] == "Bolt" and "event_id" not in part[1]["doc"]
    assert stock[1]["script"]["params"]["site_id"] == "DAL1" and stock[1]["scripted_upsert"]
    assert doc[0]["index"]["version_type"] == "external_gte"
    assert doc[0]["index"]["version"] == 1792663200000
    assert doc[1]["line_items"][0]["qty"] is None


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def bulk(self, body):
        self.calls.append(body.count("\n") // 2)
        return self.responses.pop(0)


def items(*statuses):
    return {"items": [{"update": {"status": s}} for s in statuses]}


def test_bulk_retries_429(monkeypatch):
    monkeypatch.setattr(ix.time, "sleep", lambda s: None)
    ops = [({"update": {}}, {}), ({"update": {}}, {}), ({"index": {}}, {})]
    client = FakeClient([{"items": [{"update": {"status": 200}}, {"update": {"status": 429}},
                                    {"index": {"status": 409}}]}, items(200)])
    stats = ix.bulk_with_retry(client, ops)
    assert stats == {"ok": 2, "conflict": 1, "skipped": 0, "retried": 1}
    assert client.calls == [3, 1]


def test_bulk_gives_up(monkeypatch):
    monkeypatch.setattr(ix.time, "sleep", lambda s: None)
    client = FakeClient([items(503)] * (ix.MAX_RETRIES + 1))
    with pytest.raises(RuntimeError):
        ix.bulk_with_retry(client, [({"update": {}}, {})])


def test_ensure_indices_idempotent():
    class Indices:
        def __init__(self):
            self.idx, self.aliases = set(), {}

        def exists(self, index):
            return index in self.idx

        def create(self, index, body):
            json.dumps(body)
            self.idx.add(index)

        def exists_alias(self, name):
            return name in self.aliases

        def put_alias(self, index, name):
            self.aliases[name] = index

    class C:
        indices = Indices()

    assert ensure_indices(C()) == ["parts_v1", "documents_v1"]
    assert ensure_indices(C()) == []
    assert C.indices.aliases == {"parts": "parts_v1", "documents": "documents_v1"}
