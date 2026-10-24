"""Synthetic packing slips (docs/CONTRACTS.md §13) for the simulator, stub extractor sidecars and golden set."""

from __future__ import annotations

import io
import random
from datetime import date, timedelta
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

WIDTH, HEIGHT = 1240, 1754  # A4 at 150 dpi


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in ("DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def random_truth(rng: random.Random, parts: list[dict[str, Any]], max_lines: int = 6,
                 suppliers: dict[str, str] | None = None) -> dict[str, Any]:
    """A ground-truth slip from one supplier's parts. `parts` items look like db/seed parts dicts."""
    supplier_id = rng.choice(parts)["supplier_id"]
    same = [p for p in parts if p["supplier_id"] == supplier_id]
    picks = rng.sample(same, k=min(len(same), rng.randint(1, max_lines)))
    return {
        "supplier": supplier_id,
        "supplier_name": (suppliers or {}).get(supplier_id) or same[0].get("supplier_name") or supplier_id,
        "po_number": f"PO-{rng.randint(100000, 999999)}",
        "line_items": [
            {"line_no": i + 1, "sku": p["sku"], "part_number": p["part_number"], "qty": rng.randint(1, 200),
             "description": p.get("name", "")}
            for i, p in enumerate(picks)
        ],
    }


def render_packing_slip(truth: dict[str, Any], seed: int | None = None) -> bytes:
    rng = random.Random(seed)
    img = Image.new("L", (WIDTH, HEIGHT), color=rng.randint(238, 252))
    d = ImageDraw.Draw(img)
    big, mid, small = _font(46), _font(28), _font(24)
    ink = rng.randint(0, 40)

    d.text((80, 70), truth.get("supplier_name") or truth.get("supplier") or "Supplier", fill=ink, font=big)
    d.text((80, 135), f"Supplier code: {truth.get('supplier')}", fill=ink, font=small)
    d.text((WIDTH - 480, 70), "PACKING SLIP", fill=ink, font=big)
    ship = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    d.text((WIDTH - 480, 135), f"Ship date: {ship.isoformat()}", fill=ink, font=small)
    d.text((WIDTH - 480, 170), f"Slip #: PS-{rng.randint(10000, 99999)}", fill=ink, font=small)
    d.text((80, 230), f"Customer PO: {truth.get('po_number')}", fill=ink, font=mid)
    d.text((80, 275), "Ship to: Receiving Dock, Plant 1", fill=ink, font=small)

    cols = [(80, "Line"), (180, "Part number"), (460, "SKU"), (700, "Description"), (1060, "Shipped")]
    y = 360
    d.line((70, y - 10, WIDTH - 70, y - 10), fill=ink, width=3)
    for x, label in cols:
        d.text((x, y), label, fill=ink, font=mid)
    y += 50
    d.line((70, y - 8, WIDTH - 70, y - 8), fill=ink, width=2)
    for li in truth.get("line_items", []):
        values = [str(li["line_no"]), str(li.get("part_number") or ""), str(li.get("sku") or ""),
                  str(li.get("description") or "")[:24], str(li.get("qty"))]
        for (x, _), v in zip(cols, values, strict=True):
            d.text((x, y), v, fill=ink, font=mid)
        y += 48
    d.line((70, y + 10, WIDTH - 70, y + 10), fill=ink, width=2)
    d.text((80, y + 40), f"Total lines: {len(truth.get('line_items', []))}", fill=ink, font=small)
    d.text((80, HEIGHT - 140), "Received by: ____________________   Date: __________", fill=ink, font=small)

    # Scanner/phone artefacts: noise specks, slight blur and rotation.
    for _ in range(rng.randint(200, 900)):
        x, yy = rng.randrange(WIDTH), rng.randrange(HEIGHT)
        d.point((x, yy), fill=rng.randint(80, 200))
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.0, 0.9)))
    img = img.rotate(rng.uniform(-2.0, 2.0), resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
