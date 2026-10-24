"""Deterministic stub extractor for local dev and load tests (no model calls, no cost).

With a ground-truth sidecar (hints["truth"]) it returns the truth with seeded noise: each field is corrupted
with probability `error_rate` and then gets a low confidence, so confidence routing and calibration behave
realistically. Without a sidecar it fabricates items from hints["catalog"].
"""

from __future__ import annotations

import random
import time
from typing import Any

from extract.extractors.base import ExtractionResult
from inventory_common.models import ExtractionOutput

STUB_MODEL_ID = "stub"


class StubExtractor:
    model_id = STUB_MODEL_ID
    needs_image = False

    def __init__(self, prompt_version: str = "v1", error_rate: float = 0.08):
        self.prompt_version = prompt_version
        self.error_rate = error_rate

    def _field(self, rng: random.Random, value: Any, corrupt: Any) -> dict[str, Any]:
        if value is not None and rng.random() < self.error_rate:
            return {"value": corrupt(value), "confidence": round(rng.uniform(0.3, 0.7), 3)}
        return {"value": value, "confidence": round(rng.uniform(0.86, 0.99), 3)}

    def extract(
        self, image_bytes: bytes | None, content_type: str, capture_id: str, hints: dict[str, Any]
    ) -> ExtractionResult:
        started = time.monotonic()
        rng = random.Random(capture_id)
        truth = hints.get("truth") or self._fabricate(rng, hints.get("catalog") or [])

        def bump_digit(s: str) -> str:
            chars = list(s)
            idx = [i for i, c in enumerate(chars) if c.isdigit()]
            if idx:
                i = rng.choice(idx)
                chars[i] = str((int(chars[i]) + 1) % 10)
            return "".join(chars)

        items = []
        for li in truth.get("line_items", []):
            items.append(
                {
                    "line_no": li["line_no"],
                    "sku": self._field(rng, li.get("sku"), bump_digit),
                    "part_number": self._field(rng, li.get("part_number"), bump_digit),
                    "qty": self._field(rng, li.get("qty"), lambda q: q + rng.choice([-1, 1, 10])),
                    "description": li.get("description"),
                }
            )
        output = ExtractionOutput.model_validate(
            {
                "supplier": self._field(rng, truth.get("supplier"), lambda s: s[:-1] or "X"),
                "po_number": self._field(rng, truth.get("po_number"), bump_digit),
                "line_items": items,
                "raw_text": _raw_text(truth),
            }
        )
        return ExtractionResult(
            output=output,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    @staticmethod
    def _fabricate(rng: random.Random, catalog: list[dict[str, Any]]) -> dict[str, Any]:
        if not catalog:
            return {"supplier": None, "po_number": None, "line_items": []}
        supplier = rng.choice(catalog).get("supplier_id")
        same = [p for p in catalog if p.get("supplier_id") == supplier] or catalog
        picks = rng.sample(same, k=min(len(same), rng.randint(1, 4)))
        return {
            "supplier": supplier,
            "po_number": f"PO-{rng.randint(100000, 999999)}",
            "line_items": [
                {"line_no": i + 1, "sku": p["sku"], "part_number": p.get("part_number"),
                 "qty": rng.randint(1, 50), "description": p.get("name")}
                for i, p in enumerate(picks)
            ],
        }


def _raw_text(truth: dict[str, Any]) -> str:
    lines = [f"PACKING SLIP  Supplier: {truth.get('supplier_name') or truth.get('supplier')}",
             f"PO: {truth.get('po_number')}"]
    for li in truth.get("line_items", []):
        lines.append(f"{li['line_no']}  {li.get('part_number')}  {li.get('sku')}  {li.get('description')}  "
                     f"{li.get('qty')}")
    return "\n".join(lines)
