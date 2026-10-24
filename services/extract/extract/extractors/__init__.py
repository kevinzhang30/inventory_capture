from __future__ import annotations

from extract.extractors.base import ExtractionError, ExtractionResult, Extractor
from inventory_common.config import settings

__all__ = ["ExtractionError", "ExtractionResult", "Extractor", "get_extractor"]

_cache: dict[tuple[str, str, str], Extractor] = {}


def get_extractor(kind: str | None = None, model_id: str | None = None, prompt_version: str | None = None) -> Extractor:
    kind = kind or settings.extractor
    model_id = model_id or settings.bedrock_model_id
    prompt_version = prompt_version or settings.prompt_version
    key = (kind, model_id, prompt_version)
    if key not in _cache:
        if kind == "stub":
            from extract.extractors.stub import StubExtractor

            _cache[key] = StubExtractor(prompt_version=prompt_version)
        elif kind == "bedrock":
            from extract.extractors.bedrock import BedrockExtractor

            _cache[key] = BedrockExtractor(model_id=model_id, prompt_version=prompt_version)
        else:
            raise ValueError(f"unknown extractor {kind}")
    return _cache[key]
