from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from pydantic import ValidationError

from inventory_common import auth, keys, redis_client
from inventory_common.models import Capture, ExtractionOutput, review_priority


def test_parse_groups_variants():
    assert auth._parse_groups("[operator reviewer]") == {"operator", "reviewer"}
    assert auth._parse_groups(["admin"]) == {"admin"}
    assert auth._parse_groups(None) == frozenset()


def test_principal_from_event_cognito(monkeypatch):
    monkeypatch.setattr(auth.settings, "auth_mode", "cognito")
    ev = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": "u1", "cognito:groups": "[reviewer]"}}}}}
    p = auth.principal_from_event(ev)
    assert p.user_id == "u1" and p.has_any("reviewer") and not p.has_any("operator")
    with pytest.raises(auth.AuthError):
        auth.principal_from_event({})


def test_principal_dev_headers(monkeypatch):
    monkeypatch.setattr(auth.settings, "auth_mode", "dev")
    p = auth.principal_from_event({"headers": {"X-Dev-User": "bob", "X-Dev-Groups": "operator"}})
    assert p.user_id == "bob" and p.groups == {"operator"}


def test_admin_implies_all_roles():
    assert auth.Principal("a", groups=frozenset({"admin"})).has_any("reviewer")


def test_review_score_orders_priority_then_age():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    assert keys.review_score(0, t0 + timedelta(days=30)) < keys.review_score(1, t0)
    assert keys.review_score(3, t0) < keys.review_score(3, t0 + timedelta(seconds=1))


def test_stock_cache_fill_then_versioned_update():
    redis_client._client = fakeredis.FakeRedis(decode_responses=True)
    redis_client._stock_script = None
    r = redis_client._client
    assert redis_client.write_stock("S", [("L1", 5, 2)]) == -1  # cold key: no partial hash
    assert keys.parse_stock_hash(r.hgetall("stock:S")) is None
    assert redis_client.write_stock("S", [("L1", 4, 1)], fill=True) == 1
    assert redis_client.write_stock("S", [("L1", 9, 3), ("L2", 1, 1)]) == 2
    assert redis_client.write_stock("S", [("L1", 0, 2)]) == 0  # stale
    assert keys.parse_stock_hash(r.hgetall("stock:S")) == [
        {"location_id": "L1", "on_hand": 9, "version": 3},
        {"location_id": "L2", "on_hand": 1, "version": 1},
    ]
    assert 0 < r.ttl("stock:S") <= keys.STOCK_TTL_S


BASE = {"capture_id": "0192f0c4-7d3e-7b2a-9c1d-2f3e4a5b6c7d", "site_id": "DAL1", "station_id": "S1",
        "captured_at": "2026-10-22T10:00:00Z"}


def test_capture_validates_payload_by_kind():
    Capture.model_validate({**BASE, "kind": "scan", "payload": {"sku": "SKU-1", "qty": 2, "location_id": "L"}})
    with pytest.raises(ValidationError):
        Capture.model_validate({**BASE, "kind": "scan", "payload": {"sku": "SKU-1", "qty": 0, "location_id": "L"}})
    with pytest.raises(ValidationError):
        Capture.model_validate({**BASE, "kind": "document", "payload": {"location_id": "L"}})


def test_min_confidence_and_priority():
    out = ExtractionOutput.model_validate({
        "supplier": {"value": "S", "confidence": 0.9}, "po_number": {"value": "P", "confidence": 0.95},
        "line_items": [
            {"line_no": 1, "sku": {"value": "A", "confidence": 0.6}, "qty": {"value": 1, "confidence": 0.99}}
        ],
    })
    assert out.min_confidence() == 0.6
    assert review_priority("low_confidence", 0.6) == 5
    assert review_priority("unknown_sku", 0.99) == 0
    assert review_priority("audit_sample", 0.99) == 9
