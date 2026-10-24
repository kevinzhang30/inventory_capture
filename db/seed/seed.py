"""Seed a deterministic demo catalog: sites, locations, suppliers, parts, settings.

    python -m seed.seed --parts 2000

Each part also gets a `part.upserted` outbox event so the indexer builds `parts` from the normal pipeline.
Re-running is safe (upserts).
"""

from __future__ import annotations

import argparse
import json
import random

from inventory_common.db import transaction
from inventory_common.stock import enqueue_event

SITES = [("DAL1", "Dallas Plant 1", "America/Chicago"), ("RNO1", "Reno Plant 1", "America/Los_Angeles")]
AISLES = ["A", "B", "C", "D"]
SUPPLIERS = [
    ("SUP-ACME", "Acme Fasteners"),
    ("SUP-BOLT", "BoltWorks Industrial"),
    ("SUP-GEAR", "Gearhead Components"),
    ("SUP-OHM", "Ohmic Electronics"),
    ("SUP-FLOW", "FlowLine Hydraulics"),
    ("SUP-PACK", "PackRight Packaging"),
]
CATEGORIES = {
    "fasteners": ["Hex bolt", "Socket cap screw", "Flat washer", "Lock nut", "Rivet"],
    "bearings": ["Ball bearing", "Needle bearing", "Thrust bearing"],
    "electrical": ["Relay", "Terminal block", "Fuse", "Contactor", "Cable gland"],
    "hydraulics": ["O-ring", "Hose fitting", "Check valve", "Quick coupler"],
    "packaging": ["Carton", "Stretch film", "Pallet label", "Foam insert"],
    "motion": ["Spur gear", "Timing belt", "Shaft coupling", "Linear rail"],
}
SIZES = ["M4", "M5", "M6", "M8", "M10", "M12", "1/4in", "3/8in", "1/2in", "10mm", "20mm", "40mm"]


def locations() -> list[tuple[str, str, str, str]]:
    out = []
    for site_id, _, _ in SITES:
        out.append((f"{site_id}-RECV-01", site_id, "RECV-01", "receiving"))
        out.append((f"{site_id}-STAGE-01", site_id, "STAGE-01", "staging"))
        for aisle in AISLES:
            for bay in range(1, 6):
                code = f"{aisle}{bay:02d}-01"
                out.append((f"{site_id}-{code}", site_id, code, "bin"))
    return out


def parts(n: int, rng: random.Random) -> list[dict]:
    out = []
    cats = list(CATEGORIES.items())
    for i in range(1, n + 1):
        cat, names = cats[i % len(cats)]
        sup_id, sup_name = SUPPLIERS[i % len(SUPPLIERS)]
        size = SIZES[i % len(SIZES)]
        out.append(
            {
                "sku": f"SKU-{i:06d}",
                "part_number": f"{sup_id[4:]}-{rng.randint(10, 99)}-{i:05d}",
                "name": f"{rng.choice(names)} {size}",
                "category": cat,
                "supplier_id": sup_id,
                "supplier_name": sup_name,
                "uom": "ea" if cat != "packaging" else "box",
                "reorder_point": rng.choice([0, 10, 25, 50, 100]),
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    with transaction() as conn:
        for site_id, name, tz in SITES:
            conn.execute(
                "INSERT INTO site VALUES (%s,%s,%s) ON CONFLICT (site_id) DO UPDATE SET name = EXCLUDED.name",
                (site_id, name, tz),
            )
        for loc in locations():
            conn.execute("INSERT INTO location VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING", loc)
        for sup in SUPPLIERS:
            conn.execute(
                "INSERT INTO supplier VALUES (%s,%s) ON CONFLICT (supplier_id) DO UPDATE SET name = EXCLUDED.name",
                sup,
            )
        for p in parts(args.parts, rng):
            conn.execute(
                """INSERT INTO part (sku, part_number, name, category, supplier_id, uom, reorder_point)
                   VALUES (%(sku)s, %(part_number)s, %(name)s, %(category)s, %(supplier_id)s, %(uom)s,
                           %(reorder_point)s)
                   ON CONFLICT (sku) DO UPDATE SET part_number = EXCLUDED.part_number, name = EXCLUDED.name,
                     category = EXCLUDED.category, supplier_id = EXCLUDED.supplier_id, uom = EXCLUDED.uom,
                     reorder_point = EXCLUDED.reorder_point, updated_at = now()""",
                p,
            )
            enqueue_event(conn, p["sku"], {"type": "part.upserted", **p})
        for key, value in (("confidence_threshold", 0.85), ("audit_sample_rate", 0.05)):
            conn.execute(
                "INSERT INTO app_setting (key, value) VALUES (%s, %s::jsonb) ON CONFLICT (key) DO NOTHING",
                (key, json.dumps(value)),
            )
    print(f"seeded {len(SITES)} sites, {len(locations())} locations, {args.parts} parts")


if __name__ == "__main__":
    main()
