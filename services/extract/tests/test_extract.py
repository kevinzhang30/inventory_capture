import base64
import json
import uuid

import pytest

from extract import handler as h
from extract.extractors.base import ExtractionError
from extract.extractors.bedrock import BedrockExtractor, parse_converse_response
from extract.extractors.stub import StubExtractor
from extract.routing import audit_sampled, decide_route, resolve_skus
from inventory_common.models import ExtractionOutput


def output(conf=0.95, sku="SKU-000001", qty=5, part_number=None):
    return ExtractionOutput.model_validate({
        "supplier": {"value": "SUP-ACME", "confidence": conf},
        "po_number": {"value": "PO-1", "confidence": conf},
        "line_items": [{"line_no": 1, "sku": {"value": sku, "confidence": conf},
                        "part_number": {"value": part_number, "confidence": conf},
                        "qty": {"value": qty, "confidence": conf}}],
    })


def route(out, error=None, skus=frozenset({"SKU-000001"}), loc=True, threshold=0.85, audit=0.0, cid="c1"):
    return decide_route(capture_id=cid, output=out, error=error, known_skus=set(skus), location_known=loc,
                        threshold=threshold, audit_rate=audit)


def test_routing_decisions():
    assert route(output()).action == "apply"
    assert route(None, error="boom").reason == "extraction_error"
    assert route(output(sku="SKU-999999")).reason == "unknown_sku"
    assert route(output(sku=None)).reason == "unknown_sku"
    assert route(output(), loc=False).reason == "unknown_sku"
    assert route(output(qty=0)).reason == "unknown_sku"
    r = route(output(conf=0.6))
    assert (r.reason, r.priority) == ("low_confidence", 5)
    assert route(output(), audit=1.0).reason == "audit_sample"


def test_audit_sampling_deterministic_and_rate():
    ids = [str(uuid.UUID(int=i)) for i in range(5000)]
    picks = [audit_sampled(i, 0.05) for i in ids]
    assert picks == [audit_sampled(i, 0.05) for i in ids]
    assert 0.03 < sum(picks) / len(ids) < 0.07
    assert not audit_sampled("x", 0.0)


def test_resolve_skus_from_part_number():
    out = resolve_skus(output(sku=None, part_number="ACME-1"), {"ACME-1": "SKU-000001"})
    assert out.line_items[0].sku.value == "SKU-000001"
    assert route(out).action == "apply"


TRUTH = {"supplier": "SUP-ACME", "po_number": "PO-123456",
         "line_items": [{"line_no": i, "sku": f"SKU-00000{i}", "part_number": f"ACME-1{i}", "qty": i}
                        for i in range(1, 6)]}


def test_stub_deterministic_and_noisy():
    stub = StubExtractor(error_rate=0.3)
    a = stub.extract(None, "image/png", "cap-1", {"truth": TRUTH}).output
    b = stub.extract(None, "image/png", "cap-1", {"truth": TRUTH}).output
    assert a == b
    perfect = StubExtractor(error_rate=0.0).extract(None, "image/png", "cap-2", {"truth": TRUTH}).output
    assert [li.sku.value for li in perfect.line_items] == [li["sku"] for li in TRUTH["line_items"]]
    assert perfect.min_confidence() > 0.85


def test_stub_fabricates_from_catalog():
    cat = [{"sku": f"SKU-{i:06d}", "part_number": f"P{i}", "name": "x", "supplier_id": "S"} for i in range(10)]
    out = StubExtractor().extract(None, "image/png", "cap-3", {"catalog": cat}).output
    assert 1 <= len(out.line_items) <= 4


def tool_response(data):
    return {"output": {"message": {"content": [{"toolUse": {"name": "record_packing_slip", "input": data}}]}},
            "usage": {"inputTokens": 1200, "outputTokens": 300}, "stopReason": "tool_use"}


def test_parse_converse_response():
    data = json.loads(output().model_dump_json())
    assert parse_converse_response(tool_response(data)) == output()
    with pytest.raises(ExtractionError):
        parse_converse_response({"output": {"message": {"content": [{"text": "sorry"}]}}, "stopReason": "end_turn"})
    with pytest.raises(ExtractionError):
        parse_converse_response(tool_response({"supplier": "bad"}))


def test_bedrock_extractor_request_shape():
    class FakeClient:
        def converse(self, **kw):
            self.kw = kw
            return tool_response(json.loads(output().model_dump_json()))

    client = FakeClient()
    res = BedrockExtractor("model-x", "v1", client=client).extract(b"img", "image/png", "c", {"po_number": "PO-9"})
    assert res.input_tokens == 1200 and res.model_id == "model-x"
    assert client.kw["toolConfig"]["toolChoice"] == {"tool": {"name": "record_packing_slip"}}
    assert client.kw["messages"][0]["content"][0]["image"]["format"] == "png"
    assert "PO-9" in client.kw["messages"][0]["content"][1]["text"]


def test_handler_splits_and_skips_invalid(monkeypatch):
    seen = {}
    monkeypatch.setattr(h, "process_scans", lambda s: seen.setdefault("scans", s))
    monkeypatch.setattr(h, "process_documents", lambda d: seen.setdefault("docs", d))
    monkeypatch.setattr(h, "emit_metric", lambda *a, **k: None)
    base = {"site_id": "DAL1", "station_id": "S", "captured_at": "2026-10-22T10:00:00Z",
            "received_at": "2026-10-22T10:00:01Z"}
    recs = [
        {**base, "capture_id": str(uuid.uuid4()), "kind": "scan",
         "payload": {"sku": "SKU-1", "qty": 1, "location_id": "L"}},
        {**base, "capture_id": str(uuid.uuid4()), "kind": "document",
         "payload": {"s3_key": "k", "location_id": "L"}},
        {"garbage": True},
    ]
    event = {"records": {"captures.raw-0": [
        {"topic": "captures.raw", "partition": 0, "offset": i, "key": None,
         "value": base64.b64encode(json.dumps(r).encode()).decode()} for i, r in enumerate(recs)]}}
    assert h.handler(event, None) == {"scans": 1, "documents": 1, "invalid": 1}
