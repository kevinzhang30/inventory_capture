"""Catalog/location naming that mirrors db/seed/seed.py (uses it directly when importable)."""

from __future__ import annotations

import random
from typing import Any

AISLES = ["A", "B", "C", "D"]


def parts(n: int, seed: int = 42) -> list[dict[str, Any]]:
    try:
        from seed.seed import parts as seed_parts  # same generator as the database seed

        return seed_parts(n, random.Random(seed))
    except ImportError:
        sups = ["SUP-ACME", "SUP-BOLT", "SUP-GEAR", "SUP-OHM", "SUP-FLOW", "SUP-PACK"]
        return [{"sku": f"SKU-{i:06d}", "part_number": f"{sups[i % 6][4:]}-00-{i:05d}", "name": f"Part {i}",
                 "supplier_id": sups[i % 6], "supplier_name": sups[i % 6]} for i in range(1, n + 1)]


def bin_locations(site: str) -> list[str]:
    return [f"{site}-{a}{b:02d}-01" for a in AISLES for b in range(1, 6)]


def receiving_location(site: str) -> str:
    return f"{site}-RECV-01"
