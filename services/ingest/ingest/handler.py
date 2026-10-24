"""ingest Lambda: POST /uploads (presign) and POST /captures (validate, dedupe, produce). No DB on the hot path."""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from inventory_common import keys, s3
from inventory_common.auth import AuthError, Principal, principal_from_event
from inventory_common.config import settings
from inventory_common.kafka import DeliveryTracker, flush, produce_json
from inventory_common.log import emit_metric, get_logger, trace_id_var
from inventory_common.models import Capture
from inventory_common.redis_client import get_redis

log = get_logger(__name__)

MAX_BATCH = 50
UPLOAD_EXPIRES_S = 300


def _resp(status: int, body: Any) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _error(status: int, code: str, detail: str = "") -> dict[str, Any]:
    return _resp(status, {"error": code, "detail": detail})


def _body(event: dict[str, Any]) -> Any:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    return json.loads(raw) if raw else {}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    trace_id = headers.get("x-amzn-trace-id") or uuid.uuid4().hex
    trace_id_var.set(trace_id)
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "")
    path = event.get("rawPath", "")
    try:
        principal = principal_from_event(event)
    except AuthError as exc:
        return _error(401, "unauthorized", str(exc))
    if not principal.has_any("operator"):
        return _error(403, "forbidden", "operator role required")
    try:
        body = _body(event)
    except (ValueError, UnicodeDecodeError):
        return _error(400, "invalid_json")

    if method == "POST" and path.endswith("/uploads"):
        return handle_upload(body)
    if method == "POST" and path.endswith("/captures"):
        return handle_captures(body, principal, trace_id)
    return _error(404, "not_found", f"{method} {path}")


def handle_upload(body: dict[str, Any]) -> dict[str, Any]:
    content_type = body.get("content_type", "")
    ext = s3.ALLOWED_CONTENT_TYPES.get(content_type)
    if ext is None:
        return _error(400, "unsupported_content_type", content_type)
    try:
        capture_id = uuid.UUID(str(body.get("capture_id")))
    except ValueError:
        return _error(400, "invalid_capture_id")
    now = datetime.now(UTC)
    key = f"captures/{now:%Y/%m/%d}/{capture_id}.{ext}"
    url = s3.presign_put(key, content_type, UPLOAD_EXPIRES_S)
    return _resp(
        200,
        {"url": url, "s3_key": key, "expires_in": UPLOAD_EXPIRES_S, "headers": {"Content-Type": content_type}},
    )


def _rate_limited(r: Any, station_id: str, n: int) -> int:
    """Returns how many of the n captures exceed this second's per-station budget."""
    k = keys.rate_limit(station_id, int(time.time()))
    pipe = r.pipeline()
    pipe.incrby(k, n)
    pipe.expire(k, 2)
    total = int(pipe.execute()[0])
    allowed = max(0, keys.STATION_RATE_LIMIT_PER_S - (total - n))
    return max(0, n - allowed)


def handle_captures(body: dict[str, Any], principal: Principal, trace_id: str) -> dict[str, Any]:
    items = body.get("captures") if isinstance(body, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH:
        return _error(400, "invalid_batch", f"captures must be a list of 1..{MAX_BATCH}")

    results: list[dict[str, Any]] = [{} for _ in items]
    valid: list[tuple[int, Capture]] = []
    for i, raw in enumerate(items):
        try:
            cap = Capture.model_validate(raw)
            cap.operator_id = principal.user_id
            valid.append((i, cap))
        except ValidationError as exc:
            cid = raw.get("capture_id") if isinstance(raw, dict) else None
            results[i] = {"capture_id": cid, "status": "rejected", "error": f"invalid: {exc.errors()[0]['msg']}"}

    r = get_redis()
    by_station: dict[str, list[tuple[int, Capture]]] = {}
    for i, cap in valid:
        by_station.setdefault(cap.station_id, []).append((i, cap))
    admitted: list[tuple[int, Capture]] = []
    for station, caps in by_station.items():
        over = _rate_limited(r, station, len(caps))
        for i, cap in caps[len(caps) - over:] if over else []:
            results[i] = {"capture_id": str(cap.capture_id), "status": "rejected", "error": "rate_limited"}
        admitted += caps[: len(caps) - over]

    # Dedupe: SET NX per capture id in one pipeline round trip.
    pipe = r.pipeline(transaction=False)
    for _, cap in admitted:
        pipe.set(keys.idem_capture(str(cap.capture_id)), "1", nx=True, ex=keys.IDEM_TTL_S)
    fresh_flags = pipe.execute() if admitted else []

    tracker = DeliveryTracker()
    received_at = datetime.now(UTC).isoformat()
    produced: list[tuple[int, Capture]] = []
    for (i, cap), fresh in zip(admitted, fresh_flags, strict=True):
        cid = str(cap.capture_id)
        if not fresh:
            results[i] = {"capture_id": cid, "status": "duplicate", "error": None}
            continue
        value = cap.model_dump(mode="json") | {"received_at": received_at, "trace_id": trace_id}
        produce_json(settings.topic_captures_raw, cid, value, {"trace_id": trace_id}, tracker.callback(cid))
        produced.append((i, cap))
    if produced:
        flush(10.0)

    failed: list[str] = []
    for i, cap in produced:
        cid = str(cap.capture_id)
        if cid in tracker.delivered:
            results[i] = {"capture_id": cid, "status": "accepted", "error": None}
        else:
            failed.append(cid)
            results[i] = {"capture_id": cid, "status": "rejected", "error": "produce_failed"}
    if failed:
        # Let the client retry: its retry must not be swallowed as a duplicate.
        r.delete(*[keys.idem_capture(c) for c in failed])
        log.error("kafka produce failed", extra={"count": len(failed), "errors": list(tracker.failed.values())[:3]})

    counts = {"accepted": 0, "duplicate": 0, "rejected": 0}
    for res in results:
        counts[res["status"]] += 1
    for status, n in counts.items():
        if n:
            emit_metric(f"Captures{status.capitalize()}", n)
    return _resp(202, {"results": results})
