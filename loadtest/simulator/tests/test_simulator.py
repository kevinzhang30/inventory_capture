import asyncio
import json

import httpx

from simulator import run
from simulator.catalog import bin_locations, parts
from simulator.stats import percentile


def test_percentile():
    assert percentile([], 95) == 0.0
    assert percentile(list(range(1, 101)), 50) in (50, 51)
    assert percentile([5.0], 99) == 5.0


def test_catalog_shapes():
    ps = parts(20)
    assert ps[0]["sku"] == "SKU-000001" and len(ps) == 20
    assert bin_locations("DAL1")[0] == "DAL1-A01-01"


def test_simulator_posts_paced_batches(monkeypatch):
    args = run.parse_args(["--stations", "2", "--rate", "40", "--duration", "0.6", "--doc-ratio", "0",
                           "--duplicate-ratio", "0", "--sidecar-s3-endpoint", "", "--bucket", ""])
    sent = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        sent.extend(body["captures"])
        return httpx.Response(202, json={"results": [
            {"capture_id": c["capture_id"], "status": "accepted", "error": None} for c in body["captures"]]})

    real = httpx.AsyncClient
    monkeypatch.setattr(run.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    summary = asyncio.run(run.Simulator(args).run())
    assert summary["captures_sent"] == len(sent) > 0
    assert summary["statuses"] == {"accepted": len(sent)}
    assert all(c["kind"] == "scan" and c["payload"]["qty"] > 0 for c in sent)
