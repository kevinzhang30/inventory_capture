"""Pure helpers that translate between HTTP requests and API Gateway HTTP API (payload format 2.0) shapes.

Nothing here imports FastAPI, ingest or core_api, so it is unit-testable in isolation.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
import uuid
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import parse_qsl

TEXT_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-www-form-urlencoded",
    "+json",
    "+xml",
)

JWT_AUTH_MODES = ("cognito", "cognito-local")


def is_text_content_type(content_type: str | None) -> bool:
    if not content_type:
        return True
    ct = content_type.split(";", 1)[0].strip().lower()
    return any(ct.startswith(t) or ct.endswith(t) for t in TEXT_CONTENT_TYPES)


def normalize_headers(raw: Iterable[tuple[str, str]]) -> tuple[dict[str, str], list[str]]:
    """Lowercase header names, comma-join duplicates (as API GW does) and split out cookies."""
    headers: dict[str, str] = {}
    cookies: list[str] = []
    for name, value in raw:
        key = name.lower()
        if key == "cookie":
            cookies.extend(c.strip() for c in value.split(";") if c.strip())
            continue
        headers[key] = f"{headers[key]},{value}" if key in headers else value
    return headers, cookies


def query_params(raw_query: str) -> dict[str, str] | None:
    params: dict[str, str] = {}
    for k, v in parse_qsl(raw_query, keep_blank_values=True):
        params[k] = f"{params[k]},{v}" if k in params else v
    return params or None


def decode_jwt_claims(token: str) -> dict[str, Any] | None:
    """Decode a JWT payload WITHOUT verifying the signature (local emulation only)."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    seg = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(seg))
    except (binascii.Error, ValueError):
        return None
    return claims if isinstance(claims, dict) else None


def bearer_claims(headers: Mapping[str, str]) -> dict[str, Any] | None:
    auth = headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return decode_jwt_claims(token.strip())


def build_event(
    *,
    method: str,
    path: str,
    raw_query: str = "",
    headers: Iterable[tuple[str, str]] = (),
    body: bytes | None = None,
    source_ip: str = "127.0.0.1",
    route_key: str | None = None,
    auth_mode: str = "dev",
    request_id: str | None = None,
    now_ms: int | None = None,
    stage: str = "$default",
) -> dict[str, Any]:
    """Build an API Gateway HTTP API payload-format-2.0 event."""
    hdrs, cookies = normalize_headers(headers)
    method = method.upper()
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    request_id = request_id or uuid.uuid4().hex
    route_key = route_key or f"{method} {path}"

    is_b64 = False
    body_str: str | None = None
    if body:
        if is_text_content_type(hdrs.get("content-type")):
            try:
                body_str = body.decode("utf-8")
            except UnicodeDecodeError:
                body_str, is_b64 = base64.b64encode(body).decode(), True
        else:
            body_str, is_b64 = base64.b64encode(body).decode(), True

    request_context: dict[str, Any] = {
        "accountId": "000000000000",
        "apiId": "local",
        "domainName": hdrs.get("host", "localhost"),
        "domainPrefix": hdrs.get("host", "localhost").split(".", 1)[0],
        "http": {
            "method": method,
            "path": path,
            "protocol": "HTTP/1.1",
            "sourceIp": source_ip,
            "userAgent": hdrs.get("user-agent", ""),
        },
        "requestId": request_id,
        "routeKey": route_key,
        "stage": stage,
        "time": time.strftime("%d/%b/%Y:%H:%M:%S +0000", time.gmtime(now_ms / 1000)),
        "timeEpoch": now_ms,
    }
    if auth_mode in JWT_AUTH_MODES:
        claims = bearer_claims(hdrs)
        if claims is not None:
            request_context["authorizer"] = {"jwt": {"claims": claims, "scopes": None}}

    event: dict[str, Any] = {
        "version": "2.0",
        "routeKey": route_key,
        "rawPath": path,
        "rawQueryString": raw_query,
        "headers": hdrs,
        "requestContext": request_context,
        "isBase64Encoded": is_b64,
    }
    if cookies:
        event["cookies"] = cookies
    if (qs := query_params(raw_query)) is not None:
        event["queryStringParameters"] = qs
    if body_str is not None:
        event["body"] = body_str
    return event


def translate_result(result: Any) -> tuple[int, dict[str, str], bytes, list[str]]:
    """Translate a Lambda proxy result into (status, headers, body bytes, set-cookie values).

    Mirrors API GW v2: a dict with `statusCode` is used as-is; anything else is JSON-serialized as a 200.
    """
    if not isinstance(result, dict) or "statusCode" not in result:
        body = json.dumps(result).encode()
        return 200, {"content-type": "application/json"}, body, []

    status = int(result["statusCode"])
    headers = {str(k).lower(): str(v) for k, v in (result.get("headers") or {}).items()}
    for k, vals in (result.get("multiValueHeaders") or {}).items():
        headers[str(k).lower()] = ",".join(str(v) for v in vals)
    raw = result.get("body")
    if raw is None:
        body = b""
    elif result.get("isBase64Encoded"):
        body = base64.b64decode(raw)
    elif isinstance(raw, bytes):
        body = raw
    elif isinstance(raw, str):
        body = raw.encode()
    else:
        body = json.dumps(raw).encode()
    if body and "content-type" not in headers:
        headers["content-type"] = "application/json"
    return status, headers, body, [str(c) for c in result.get("cookies") or []]
