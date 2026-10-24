"""Confidence routing (design §6.2). Pure functions: no I/O."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from inventory_common.models import ExtractionOutput, review_priority


@dataclass(frozen=True)
class Route:
    action: str  # "apply" | "review"
    reason: str | None = None
    priority: int | None = None


def audit_sampled(capture_id: str, rate: float) -> bool:
    """Deterministic per capture, so a redelivered capture gets the same decision."""
    if rate <= 0:
        return False
    h = int(hashlib.sha256(capture_id.encode()).hexdigest()[:8], 16)
    return h / 0xFFFFFFFF < rate


def decide_route(
    *,
    capture_id: str,
    output: ExtractionOutput | None,
    error: str | None,
    known_skus: set[str],
    location_known: bool,
    threshold: float,
    audit_rate: float,
) -> Route:
    if error or output is None:
        return Route("review", "extraction_error", review_priority("extraction_error", None))
    if not output.line_items or not location_known:
        return Route("review", "unknown_sku", review_priority("unknown_sku", None))
    for li in output.line_items:
        if not li.sku.value or li.sku.value not in known_skus or not isinstance(li.qty.value, int) or li.qty.value <= 0:
            return Route("review", "unknown_sku", review_priority("unknown_sku", None))
    min_conf = output.min_confidence()
    if min_conf < threshold:
        return Route("review", "low_confidence", review_priority("low_confidence", min_conf))
    if audit_sampled(capture_id, audit_rate):
        return Route("review", "audit_sample", review_priority("audit_sample", min_conf))
    return Route("apply")


def resolve_skus(output: ExtractionOutput, sku_by_part_number: dict[str, str]) -> ExtractionOutput:
    """Fill missing SKUs from the supplier part number (confidence inherits the part number's)."""
    resolved = output.model_copy(deep=True)
    for li in resolved.line_items:
        pn = li.part_number.value
        if not li.sku.value and pn and pn in sku_by_part_number:
            li.sku.value = sku_by_part_number[pn]
            li.sku.confidence = li.part_number.confidence
    return resolved
