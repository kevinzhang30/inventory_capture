"""Rebuild derived stores from the source of truth (ADR-001: Redis and OpenSearch are derived).

    python -m ops.rebuild cache [--warm]        # drop stock:* keys (reads refill), optionally refill all now
    python -m ops.rebuild index --version 2     # build parts_v2/documents_v2 from Postgres, swap aliases

The Kafka-replay variant (new consumer group from TRIM_HORIZON) is driven by Terraform's
`consumer_group_generation` in AWS, or locally by starting a runner with a fresh --group.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from indexer.handler import site_of
from indexer.mappings import ensure_indices, index_body
from inventory_common.db import connection
from inventory_common.log import get_logger
from inventory_common.redis_client import get_redis, write_stock
from inventory_common.search import DOCUMENTS_ALIAS, PARTS_ALIAS, get_opensearch

log = get_logger("ops.rebuild")


def rebuild_cache(warm: bool) -> dict[str, int]:
    r = get_redis()
    deleted = 0
    batch: list[str] = []
    for key in r.scan_iter(match="stock:*", count=1000):
        batch.append(key)
        if len(batch) >= 500:
            deleted += sum(r.delete(k) for k in batch)  # per-key: cluster-safe
            batch = []
    deleted += sum(r.delete(k) for k in batch)
    warmed = 0
    if warm:
        with connection() as conn:
            rows: dict[str, list[tuple[str, int, int]]] = {}
            for row in conn.execute("SELECT sku, location_id, on_hand, version FROM stock_level ORDER BY sku"):
                rows.setdefault(row["sku"], []).append((row["location_id"], row["on_hand"], row["version"]))
            conn.rollback()
        for sku, locs in rows.items():
            write_stock(sku, locs, fill=True)
            warmed += 1
    return {"deleted": deleted, "warmed": warmed}


def _part_docs() -> Iterator[dict[str, Any]]:
    now = datetime.now(UTC).isoformat()
    with connection() as conn:
        cur = conn.cursor(name="parts_export")
        cur.execute(
            """SELECT p.sku, p.part_number, p.name, p.category, p.supplier_id, s.name AS supplier_name, p.uom,
                      p.reorder_point,
                      COALESCE(json_agg(json_build_object('location_id', sl.location_id, 'on_hand', sl.on_hand,
                                                          'version', sl.version))
                               FILTER (WHERE sl.location_id IS NOT NULL), '[]') AS locations
               FROM part p LEFT JOIN supplier s USING (supplier_id)
               LEFT JOIN stock_level sl ON sl.sku = p.sku
               GROUP BY p.sku, s.name"""
        )
        for row in cur:
            locs = [{**loc, "site_id": site_of(loc["location_id"])} for loc in row.pop("locations")]
            yield {**row, "locations": locs, "on_hand_total": sum(loc["on_hand"] for loc in locs),
                   "sites": sorted({loc["site_id"] for loc in locs if loc["on_hand"] > 0}), "updated_at": now}
        conn.rollback()


def _document_docs() -> Iterator[dict[str, Any]]:
    status_map = {"applied": "auto_applied", "pending_review": "pending_review", "reviewed": "reviewed"}
    with connection() as conn:
        cur = conn.cursor(name="docs_export")
        cur.execute(
            """SELECT DISTINCT ON (c.capture_id) c.capture_id, c.site_id, c.status, c.captured_at,
                      e.extraction_id, e.output, gt.corrected
               FROM capture c JOIN extraction e ON e.capture_id = c.capture_id
               LEFT JOIN ground_truth gt ON gt.extraction_id = e.extraction_id
               WHERE c.kind = 'document'
               ORDER BY c.capture_id, e.created_at DESC"""
        )
        for row in cur:
            out = row["output"] or {}
            gt = row["corrected"]
            items = gt["line_items"] if gt else [
                {"line_no": li["line_no"], "sku": li["sku"]["value"], "part_number": li["part_number"]["value"],
                 "qty": li["qty"]["value"], "description": li.get("description")}
                for li in out.get("line_items", [])
            ]
            yield {
                "capture_id": str(row["capture_id"]), "extraction_id": str(row["extraction_id"]),
                "site_id": row["site_id"],
                "supplier": gt["supplier"] if gt else (out.get("supplier") or {}).get("value"),
                "po_number": gt["po_number"] if gt else (out.get("po_number") or {}).get("value"),
                "raw_text": out.get("raw_text", ""), "status": status_map.get(row["status"], row["status"]),
                "captured_at": row["captured_at"].isoformat(),
                "line_items": [{k: li.get(k) for k in ("line_no", "sku", "part_number", "qty", "description")}
                               for li in items],
            }
        conn.rollback()


def _bulk(client: Any, index: str, docs: Iterator[dict[str, Any]], id_field: str) -> int:
    n = 0
    buf: list[str] = []
    for d in docs:
        buf.append(json.dumps({"index": {"_index": index, "_id": d[id_field]}}))
        buf.append(json.dumps(d, default=str))
        n += 1
        if len(buf) >= 2000:
            client.bulk(body="\n".join(buf) + "\n")
            buf = []
    if buf:
        client.bulk(body="\n".join(buf) + "\n")
    return n


def rebuild_index(version: int) -> dict[str, Any]:
    client = get_opensearch()
    parts_idx, docs_idx = f"parts_v{version}", f"documents_v{version}"
    for idx, kind in ((parts_idx, "parts"), (docs_idx, "documents")):
        if client.indices.exists(index=idx):
            raise SystemExit(f"{idx} already exists; pick a new --version")
        body = index_body(kind)
        body["settings"]["index"]["refresh_interval"] = "-1"  # fast bulk load
        client.indices.create(index=idx, body=body)
    n_parts = _bulk(client, parts_idx, _part_docs(), "sku")
    n_docs = _bulk(client, docs_idx, _document_docs(), "capture_id")
    for idx in (parts_idx, docs_idx):
        client.indices.put_settings(index=idx, body={"index": {"refresh_interval": "1s"}})
        client.indices.refresh(index=idx)
    actions = []
    for alias, idx in ((PARTS_ALIAS, parts_idx), (DOCUMENTS_ALIAS, docs_idx)):
        if client.indices.exists_alias(name=alias):
            for old in client.indices.get_alias(name=alias):
                actions.append({"remove": {"index": old, "alias": alias}})
        actions.append({"add": {"index": idx, "alias": alias}})
    client.indices.update_aliases(body={"actions": actions})  # atomic swap
    return {"parts": n_parts, "documents": n_docs, "aliases": {PARTS_ALIAS: parts_idx, DOCUMENTS_ALIAS: docs_idx}}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cache")
    c.add_argument("--warm", action="store_true")
    i = sub.add_parser("index")
    i.add_argument("--version", type=int, required=True)
    sub.add_parser("ensure-indices")
    args = ap.parse_args()
    if args.cmd == "cache":
        print(rebuild_cache(args.warm))
    elif args.cmd == "index":
        print(rebuild_index(args.version))
    else:
        print(ensure_indices(get_opensearch()))


if __name__ == "__main__":
    main()
