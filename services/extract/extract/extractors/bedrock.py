"""Bedrock (Claude) extractor using the Converse API with a forced tool call as the JSON schema."""

from __future__ import annotations

import time
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from pydantic import ValidationError

from extract.extractors.base import ExtractionError, ExtractionResult
from extract.prompts import get_prompt
from inventory_common.config import settings
from inventory_common.models import ExtractionOutput

TOOL_NAME = "record_packing_slip"
_RETRYABLE = {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException",
              "InternalServerException", "ModelTimeoutException"}


def _field_schema(value_type: str | list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "value": {"type": value_type},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["value", "confidence"],
    }


TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "supplier": _field_schema(["string", "null"]),
        "po_number": _field_schema(["string", "null"]),
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_no": {"type": "integer"},
                    "sku": _field_schema(["string", "null"]),
                    "part_number": _field_schema(["string", "null"]),
                    "qty": _field_schema(["integer", "null"]),
                    "description": {"type": ["string", "null"]},
                },
                "required": ["line_no", "sku", "part_number", "qty"],
            },
        },
        "raw_text": {"type": "string"},
    },
    "required": ["supplier", "po_number", "line_items", "raw_text"],
}


class TransientModelError(Exception):
    """Throttled or unavailable after retries; the Kafka batch should be retried later."""


class BedrockExtractor:
    needs_image = True

    def __init__(self, model_id: str, prompt_version: str, client: Any = None):
        self.model_id = model_id
        self.prompt_version = prompt_version
        self.prompt = get_prompt(prompt_version)
        self.client = client or boto3.client(
            "bedrock-runtime",
            region_name=settings.aws_region,
            config=Config(retries={"mode": "adaptive", "max_attempts": 6}, read_timeout=120),
        )

    def _content_block(self, image_bytes: bytes, content_type: str) -> dict[str, Any]:
        if content_type == "application/pdf":
            return {"document": {"format": "pdf", "name": "packing-slip", "source": {"bytes": image_bytes}}}
        fmt = {"image/jpeg": "jpeg", "image/png": "png"}.get(content_type)
        if fmt is None:
            raise ExtractionError(f"unsupported content type {content_type}")
        return {"image": {"format": fmt, "source": {"bytes": image_bytes}}}

    def extract(
        self, image_bytes: bytes | None, content_type: str, capture_id: str, hints: dict[str, Any]
    ) -> ExtractionResult:
        if not image_bytes:
            raise ExtractionError("no image bytes")
        hint_lines = ""
        if hints.get("po_number"):
            hint_lines += f"\nOperator hint: the PO number is probably {hints['po_number']}."
        if hints.get("supplier_names"):
            hint_lines += "\nKnown suppliers (code: name): " + "; ".join(hints["supplier_names"]) + "."
        started = time.monotonic()
        try:
            resp = self.client.converse(
                modelId=self.model_id,
                system=[{"text": self.prompt.system}],
                messages=[{
                    "role": "user",
                    "content": [
                        self._content_block(image_bytes, content_type),
                        {"text": self.prompt.instructions.format(hints=hint_lines)},
                    ],
                }],
                toolConfig={
                    "tools": [{"toolSpec": {
                        "name": TOOL_NAME,
                        "description": "Record the structured contents of a packing slip.",
                        "inputSchema": {"json": TOOL_SCHEMA},
                    }}],
                    "toolChoice": {"tool": {"name": TOOL_NAME}},
                },
                inferenceConfig={"maxTokens": 4096, "temperature": 0},
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _RETRYABLE:
                raise TransientModelError(code) from exc
            raise ExtractionError(f"bedrock {code}: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        output = parse_converse_response(resp)
        usage = resp.get("usage") or {}
        return ExtractionResult(
            output=output,
            model_id=self.model_id,
            prompt_version=self.prompt_version,
            latency_ms=latency_ms,
            input_tokens=int(usage.get("inputTokens", 0)),
            output_tokens=int(usage.get("outputTokens", 0)),
        )


def parse_converse_response(resp: dict[str, Any]) -> ExtractionOutput:
    for block in (resp.get("output") or {}).get("message", {}).get("content", []):
        tool_use = block.get("toolUse")
        if tool_use and tool_use.get("name") == TOOL_NAME:
            data = tool_use.get("input") or {}
            for i, li in enumerate(data.get("line_items") or [], start=1):
                li.setdefault("line_no", i)
                li.setdefault("part_number", {"value": None, "confidence": 0.0})
            try:
                return ExtractionOutput.model_validate(data)
            except ValidationError as exc:
                raise ExtractionError(f"tool output failed validation: {exc.errors()[:3]}") from exc
    raise ExtractionError(f"model did not call {TOOL_NAME} (stopReason={resp.get('stopReason')})")
