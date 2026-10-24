"""indexer Lambda (MSK inventory.events): one OpenSearch _bulk per invocation. All operations are idempotent."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from inventory_common.lambda_events import iter_kafka_records
from inventory_common.log import emit_metric, get_logger
from inventory_common.search import DOCUMENTS_ALIAS, PARTS_ALIAS, get_opensearch

log = get_logger(__name__)

MAX_RETRIES = 4
PART_FIELDS = ("sku", "part_number", "name", "category", "supplier_id", "supplier_name", "uom", "reorder_point")

# Upserts the nested location only when the event version is newer; recomputes totals. Runs on an empty
# source for a new doc (scripted_upsert), so stock events may arrive before part.upserted.
STOCK_SCRIPT = """
if (ctx._source.locations == null) { ctx._source.locations = new ArrayList(); }
ctx._source.sku = params.sku;
boolean found = false;
boolean changed = false;
for (def l : ctx._source.locations) {
  if (l.location_id == params.location_id) {
    found = true;
    if (params.version > l.version) { l.on_hand = params.on_hand; l.version = params.version; changed = true; }
  }
}
if (!found) {
  Map l = new HashMap();
  l.location_id = params.location_id; l.site_id = params.site_id; l.on_hand = params.on_hand;
  l.version = params.version;
  ctx._source.locations.add(l);
  changed = true;
}
if (changed) {
  int total = 0;
  Set sites = new TreeSet();
  for (def l : ctx._source.locations) { total += l.on_hand; if (l.on_hand > 0) { sites.add(l.site_id); } }
  ctx._source.on_hand_total = total;
  ctx._source.sites = new ArrayList(sites);
  ctx._source.updated_at = params.updated_at;
} else {
  ctx.op = 'none';
}
"""


def site_of(location_id: str) -> str:
    """Location IDs are `<site>-<bin>` (db/seed)."""
    return location_id.split("-", 1)[0]


def _epoch_ms(iso: str | None) -> int:
    if not iso:
        return int(time.time() * 1000)
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def build_operations(events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    ops: list[tuple[dict[str, Any], dict[str, Any]]] = []
    now = datetime.now(UTC).isoformat()
    for e in events:
        t = e.get("type")
        if t == "part.upserted":
            doc = {k: e[k] for k in PART_FIELDS if k in e} | {"updated_at": now}
            ops.append(({"update": {"_index": PARTS_ALIAS, "_id": e["sku"], "retry_on_conflict": 3}},
                        {"doc": doc, "doc_as_upsert": True}))
        elif t == "stock.changed":
            params = {
                "sku": e["sku"], "location_id": e["location_id"], "site_id": site_of(e["location_id"]),
                "on_hand": int(e["on_hand"]), "version": int(e["version"]), "updated_at": now,
            }
            ops.append(({"update": {"_index": PARTS_ALIAS, "_id": e["sku"], "retry_on_conflict": 5}},
                        {"scripted_upsert": True, "upsert": {},
                         "script": {"lang": "painless", "source": STOCK_SCRIPT, "params": params}}))
        elif t == "document.extracted":
            doc = {k: e.get(k) for k in ("capture_id", "extraction_id", "site_id", "supplier", "po_number",
                                         "raw_text", "status", "captured_at", "occurred_at")}
            doc["line_items"] = [
                {**li, "qty": li["qty"] if isinstance(li.get("qty"), int) else None} for li in e.get("line_items", [])
            ]
            # External versioning by event time: an older status can never overwrite a newer one.
            ops.append(({"index": {"_index": DOCUMENTS_ALIAS, "_id": e["capture_id"],
                                   "version": _epoch_ms(e.get("occurred_at")), "version_type": "external_gte"}},
                        doc))
    return ops


def _ndjson(ops: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    return "".join(json.dumps(a) + "\n" + json.dumps(s) + "\n" for a, s in ops)


def bulk_with_retry(client: Any, ops: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, int]:
    stats = {"ok": 0, "conflict": 0, "skipped": 0, "retried": 0}
    pending = ops
    for attempt in range(MAX_RETRIES + 1):
        resp = client.bulk(body=_ndjson(pending))
        retry: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for op, item in zip(pending, resp["items"], strict=True):
            res = next(iter(item.values()))
            status = int(res.get("status", 500))
            if status < 300:
                stats["ok"] += 1
            elif status == 409 and "index" in op[0]:
                stats["conflict"] += 1  # older document event; newer version already indexed
            elif status == 429 or status >= 500:
                retry.append(op)
            else:
                stats["skipped"] += 1
                log.error("bulk item rejected", extra={"status": status, "error": str(res.get("error"))[:500]})
        if not retry:
            return stats
        stats["retried"] += len(retry)
        pending = retry
        time.sleep(min(0.2 * 2**attempt, 3))
    raise RuntimeError(f"{len(pending)} bulk items still failing after {MAX_RETRIES} retries")


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    events = []
    for rec in iter_kafka_records(event):
        try:
            e = rec.json()
        except ValueError:
            continue
        if isinstance(e, dict):
            events.append(e)
    ops = build_operations(events)
    if not ops:
        return {"ok": 0}
    started = time.monotonic()
    stats = bulk_with_retry(get_opensearch(), ops)
    emit_metric("IndexBulkLatency", (time.monotonic() - started) * 1000, "Milliseconds")
    emit_metric("IndexBulkItems", len(ops))
    if stats["retried"]:
        emit_metric("IndexBulkRejected", stats["retried"])
    return stats
