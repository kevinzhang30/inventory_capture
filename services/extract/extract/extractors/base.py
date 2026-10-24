"""Extractor interface shared by the stub, Bedrock and the offline eval harness."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from inventory_common.models import ExtractionOutput


@dataclass
class ExtractionResult:
    output: ExtractionOutput
    model_id: str
    prompt_version: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0


class ExtractionError(Exception):
    """The model produced no usable output (permanent for this capture; routed to review)."""


class Extractor(Protocol):
    model_id: str
    prompt_version: str
    needs_image: bool

    def extract(
        self, image_bytes: bytes | None, content_type: str, capture_id: str, hints: dict[str, Any]
    ) -> ExtractionResult: ...
