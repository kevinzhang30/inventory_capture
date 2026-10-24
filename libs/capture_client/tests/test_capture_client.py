import json
import random

import httpx
import pytest

from capture_client.api import ApiClient, DevAuth
from capture_client.outbox import BACKOFF_CAP_S, Outbox, backoff_delay
from capture_client.slips import random_truth, render_packing_slip
from capture_client.sync import SyncEngine


@pytest.fixture()
def outbox(tmp_path):
    ob = Outbox(tmp_path / "outbox.db")
    yield ob
    ob.close()


def test_backoff_bounds():
    rng = random.Random(1)
    assert all(0 <= backoff_delay(a, rng) <= min(BACKOFF_CAP_S, 2**a) for a in range(30))


def test_outbox_state_machine(outbox, tmp_path):
    scan = outbox.add_scan("DAL1", "ST1", "SKU-000001", 3, "DAL1-A01-01")
    img = tmp_path / "slip.png"
    img.write_bytes(b"png")
    doc = outbox.add_document("DAL1", "ST1", img, "image/png", "DAL1-RECV-01", po_number="PO-1")
    assert [i.capture_id for i in outbox.due_batch()] == [scan]  # document waits for upload
    assert [i.capture_id for i in outbox.due_uploads()] == [doc]
    outbox.mark_uploaded(doc, "captures/x.png")
    batch = outbox.due_batch()
    assert {i.capture_id for i in batch} == {scan, doc}
    capture = next(i for i in batch if i.capture_id == doc).to_capture()
    assert capture["payload"] == {"location_id": "DAL1-RECV-01", "po_number": "PO-1", "s3_key": "captures/x.png",
                                  "content_type": "image/png"}
    outbox.schedule_retry([scan], "boom", now=1000)
    assert [i.capture_id for i in outbox.due_batch(now=1000)] == [doc]  # scan is backing off
    assert {i.capture_id for i in outbox.due_batch(now=1000 + 10)} == {scan, doc}
    outbox.mark_synced([scan, doc])
    assert outbox.stats()["synced"] == 2


def make_api(handler):
    return ApiClient("http://api", DevAuth(), transport=httpx.MockTransport(handler))


def test_sync_maps_statuses(outbox):
    ids = [outbox.add_scan("DAL1", "ST1", f"SKU-00000{i}", 1, "L") for i in range(4)]
    statuses = {ids[0]: ("accepted", None), ids[1]: ("duplicate", None), ids[2]: ("rejected", "produce_failed"),
                ids[3]: ("rejected", "invalid: bad")}

    def handler(req):
        body = json.loads(req.content)
        return httpx.Response(202, json={"results": [
            {"capture_id": c["capture_id"], "status": statuses[c["capture_id"]][0],
             "error": statuses[c["capture_id"]][1]} for c in body["captures"]]})

    st = SyncEngine(outbox, make_api(handler)).sync_once()
    assert (st.synced, st.rejected, st.retried) == (2, 1, 1)
    assert st.counts["synced"] == 2 and st.counts["rejected"] == 1 and st.counts["pending"] == 1


def test_sync_offline_and_5xx_schedule_retry(outbox):
    outbox.add_scan("DAL1", "ST1", "SKU-000001", 1, "L")

    def offline(req):
        raise httpx.ConnectError("no route")

    st = SyncEngine(outbox, make_api(offline)).sync_once()
    assert not st.online and outbox.recent()[0].attempts == 1

    outbox.add_scan("DAL1", "ST1", "SKU-000002", 1, "L")
    st = SyncEngine(outbox, make_api(lambda r: httpx.Response(503, text="busy"))).sync_once()
    assert st.retried >= 1 and st.counts["rejected"] == 0


def test_sync_uploads_documents_first(outbox, tmp_path):
    img = tmp_path / "s.png"
    img.write_bytes(b"x")
    doc = outbox.add_document("DAL1", "ST1", img, "image/png", "L")
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path))
        if req.url.path == "/uploads":
            return httpx.Response(200, json={"url": "http://s3/put", "s3_key": "k", "headers": {}})
        if req.method == "PUT":
            return httpx.Response(200)
        return httpx.Response(202, json={"results": [{"capture_id": doc, "status": "accepted", "error": None}]})

    st = SyncEngine(outbox, make_api(handler)).sync_once()
    assert st.uploaded == 1 and st.synced == 1
    assert seen == [("POST", "/uploads"), ("PUT", "/put"), ("POST", "/captures")]


def test_slip_render_is_deterministic_png():
    parts = [{"sku": f"SKU-{i:06d}", "part_number": f"ACME-1-{i}", "name": "Bolt", "supplier_id": "SUP-ACME"}
             for i in range(10)]
    truth = random_truth(random.Random(3), parts)
    a, b = render_packing_slip(truth, seed=7), render_packing_slip(truth, seed=7)
    assert a[:8] == b"\x89PNG\r\n\x1a\n" and a == b
    assert 1 <= len(truth["line_items"]) <= 6
