import base64
import json
import os

os.environ["GATEWAY_LAZY"] = "1"

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import create_app  # noqa: E402
from gateway.events import build_event, decode_jwt_claims, translate_result  # noqa: E402


def test_build_event_shapes():
    ev = build_event(method="post", path="/captures", raw_query="a=1&a=2", body=b'{"x":1}',
                     headers=[("Content-Type", "application/json"), ("X-Dev-User", "u"), ("Cookie", "a=b; c=d")],
                     now_ms=0, request_id="r")
    assert ev["version"] == "2.0" and ev["routeKey"] == "POST /captures"
    assert ev["headers"]["x-dev-user"] == "u" and ev["cookies"] == ["a=b", "c=d"]
    assert ev["queryStringParameters"] == {"a": "1,2"}
    assert ev["body"] == '{"x":1}' and ev["isBase64Encoded"] is False
    binary = build_event(method="POST", path="/x", headers=[("content-type", "image/png")], body=b"\x89PNG")
    assert binary["isBase64Encoded"] and base64.b64decode(binary["body"]) == b"\x89PNG"


def test_jwt_claims_in_cognito_mode():
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "u1"}).encode()).decode().rstrip("=")
    token = f"h.{payload}.s"
    assert decode_jwt_claims(token) == {"sub": "u1"}
    ev = build_event(method="GET", path="/", headers=[("authorization", f"Bearer {token}")], auth_mode="cognito")
    assert ev["requestContext"]["authorizer"]["jwt"]["claims"]["sub"] == "u1"


def test_translate_result():
    assert translate_result({"statusCode": 202, "body": "{}"})[:3] == (202, {"content-type": "application/json"},
                                                                       b"{}")
    assert translate_result({"a": 1})[0] == 200


def test_routes_ingest_and_core():
    seen = {}

    def fake_ingest(event, ctx):
        seen["event"] = event
        return {"statusCode": 202, "headers": {"content-type": "application/json"}, "body": '{"ok": true}'}

    core = FastAPI()

    @core.get("/health")
    def health():
        return {"status": "ok"}

    client = TestClient(create_app(fake_ingest, core))
    r = client.post("/captures", json={"captures": []}, headers={"x-dev-user": "u"})
    assert r.status_code == 202 and r.json() == {"ok": True}
    assert seen["event"]["rawPath"] == "/captures" and seen["event"]["headers"]["x-dev-user"] == "u"
    assert client.get("/health").json() == {"status": "ok"}
