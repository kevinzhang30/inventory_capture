"""OpenSearch index definitions (docs/CONTRACTS.md §8). Versioned indices behind stable aliases."""

from __future__ import annotations

import os
from typing import Any

from inventory_common.search import DOCUMENTS_ALIAS, PARTS_ALIAS

PARTS_INDEX = "parts_v1"
DOCUMENTS_INDEX = "documents_v1"
REFRESH_INTERVAL = os.environ.get("INDEX_REFRESH_INTERVAL", "1s")


def _settings() -> dict[str, Any]:
    return {
        "index": {"number_of_shards": 1, "number_of_replicas": 0, "refresh_interval": REFRESH_INTERVAL},
        "analysis": {
            "tokenizer": {
                "edge": {"type": "edge_ngram", "min_gram": 2, "max_gram": 20, "token_chars": ["letter", "digit"]}
            },
            "normalizer": {"lower": {"type": "custom", "filter": ["lowercase"]}},
            "analyzer": {
                "partno_edge": {"type": "custom", "tokenizer": "edge", "filter": ["lowercase"]},
                "partno_search": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase"]},
            },
        },
    }


PARTS_MAPPINGS: dict[str, Any] = {
    "dynamic": "strict",
    "properties": {
        "sku": {"type": "keyword", "normalizer": "lower"},
        "part_number": {
            "type": "text",
            "analyzer": "partno_search",
            "fields": {
                "ngram": {"type": "text", "analyzer": "partno_edge", "search_analyzer": "partno_search"},
                "raw": {"type": "keyword", "normalizer": "lower"},
            },
        },
        "name": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
        "category": {"type": "keyword"},
        "supplier_id": {"type": "keyword"},
        "supplier_name": {"type": "keyword"},
        "uom": {"type": "keyword"},
        "reorder_point": {"type": "integer"},
        "on_hand_total": {"type": "integer"},
        "sites": {"type": "keyword"},
        "locations": {
            "type": "nested",
            "properties": {
                "location_id": {"type": "keyword"},
                "site_id": {"type": "keyword"},
                "on_hand": {"type": "integer"},
                "version": {"type": "long"},
            },
        },
        "updated_at": {"type": "date"},
    },
}

DOCUMENTS_MAPPINGS: dict[str, Any] = {
    "dynamic": "strict",
    "properties": {
        "capture_id": {"type": "keyword"},
        "extraction_id": {"type": "keyword"},
        "site_id": {"type": "keyword"},
        "supplier": {"type": "keyword"},
        "po_number": {"type": "keyword", "fields": {"text": {"type": "text"}}},
        "raw_text": {"type": "text"},
        "status": {"type": "keyword"},
        "captured_at": {"type": "date"},
        "occurred_at": {"type": "date"},
        "line_items": {
            "type": "nested",
            "properties": {
                "line_no": {"type": "integer"},
                "sku": {"type": "keyword"},
                "part_number": {"type": "keyword"},
                "qty": {"type": "integer"},
                "description": {"type": "text"},
            },
        },
    },
}


def index_body(kind: str) -> dict[str, Any]:
    return {"settings": _settings(), "mappings": PARTS_MAPPINGS if kind == "parts" else DOCUMENTS_MAPPINGS}


def ensure_indices(client: Any, parts_index: str = PARTS_INDEX, documents_index: str = DOCUMENTS_INDEX) -> list[str]:
    """Create indices and point aliases at them if the aliases do not exist yet. Returns created names."""
    created = []
    for alias, index, kind in ((PARTS_ALIAS, parts_index, "parts"), (DOCUMENTS_ALIAS, documents_index, "documents")):
        if not client.indices.exists(index=index):
            client.indices.create(index=index, body=index_body(kind))
            created.append(index)
        if not client.indices.exists_alias(name=alias):
            client.indices.put_alias(index=index, name=alias)
    return created
