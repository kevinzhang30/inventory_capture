"""OpenSearch queries for parts and documents (F6)."""

from __future__ import annotations

from typing import Any

from inventory_common.search import DOCUMENTS_ALIAS, PARTS_ALIAS, get_opensearch

PART_SOURCE = ["sku", "part_number", "name", "category", "supplier_id", "supplier_name", "uom", "reorder_point",
               "on_hand_total", "sites", "locations"]


def _page(page: int, size: int) -> tuple[int, int]:
    size = max(1, min(size, 100))
    return (max(page, 1) - 1) * size, size


def _facets(aggs: dict[str, Any], names: list[str]) -> dict[str, list[dict[str, Any]]]:
    return {n: [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get(n, {}).get("buckets", [])]
            for n in names}


def parts_query(q: str | None, category: list[str], supplier: list[str], site: list[str],
                page: int, size: int) -> dict[str, Any]:
    must: list[dict[str, Any]] = []
    if q:
        must.append({"bool": {"should": [
            {"term": {"sku": {"value": q.lower(), "boost": 10}}},
            {"term": {"part_number.raw": {"value": q.lower(), "boost": 8}}},
            {"match": {"part_number.ngram": {"query": q, "boost": 3}}},
            {"match": {"name": {"query": q, "fuzziness": "AUTO", "boost": 1}}},
            {"match": {"supplier_name": {"query": q, "boost": 0.5}}},
        ], "minimum_should_match": 1}})
    filters = []
    for field, values in (("category", category), ("supplier_id", supplier), ("sites", site)):
        if values:
            filters.append({"terms": {field: values}})
    frm, size = _page(page, size)
    return {
        "from": frm, "size": size, "track_total_hits": True, "_source": PART_SOURCE,
        "query": {"bool": {"must": must or [{"match_all": {}}], "filter": filters}},
        "sort": ["_score", {"sku": "asc"}],
        "aggs": {
            "category": {"terms": {"field": "category", "size": 20}},
            "supplier": {"terms": {"field": "supplier_id", "size": 20}},
            "site": {"terms": {"field": "sites", "size": 20}},
        },
    }


def search_parts(q: str | None, category: list[str], supplier: list[str], site: list[str],
                 page: int, size: int) -> dict[str, Any]:
    resp = get_opensearch().search(index=PARTS_ALIAS, body=parts_query(q, category, supplier, site, page, size))
    return {
        "total": resp["hits"]["total"]["value"],
        "items": [h["_source"] | {"score": h.get("_score")} for h in resp["hits"]["hits"]],
        "facets": _facets(resp.get("aggregations", {}), ["category", "supplier", "site"]),
    }


def documents_query(q: str | None, supplier: list[str], date_from: str | None, date_to: str | None,
                    page: int, size: int) -> dict[str, Any]:
    must: list[dict[str, Any]] = []
    if q:
        must.append({"multi_match": {"query": q, "fields": ["po_number^5", "po_number.text^3", "supplier^2",
                                                            "raw_text"], "fuzziness": "AUTO"}})
    filters: list[dict[str, Any]] = []
    if supplier:
        filters.append({"terms": {"supplier": supplier}})
    if date_from or date_to:
        filters.append({"range": {"captured_at": {k: v for k, v in (("gte", date_from), ("lte", date_to)) if v}}})
    frm, size = _page(page, size)
    return {
        "from": frm, "size": size, "track_total_hits": True,
        "query": {"bool": {"must": must or [{"match_all": {}}], "filter": filters}},
        "sort": ["_score", {"captured_at": "desc"}],
        "aggs": {"supplier": {"terms": {"field": "supplier", "size": 20}}},
    }


def search_documents(q: str | None, supplier: list[str], date_from: str | None, date_to: str | None,
                     page: int, size: int) -> dict[str, Any]:
    resp = get_opensearch().search(index=DOCUMENTS_ALIAS,
                                   body=documents_query(q, supplier, date_from, date_to, page, size))
    return {
        "total": resp["hits"]["total"]["value"],
        "items": [h["_source"] for h in resp["hits"]["hits"]],
        "facets": _facets(resp.get("aggregations", {}), ["supplier"]),
    }
