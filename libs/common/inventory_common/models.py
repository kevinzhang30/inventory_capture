"""Pydantic models for wire contracts (docs/CONTRACTS.md §2-§5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScanPayload(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    qty: int = Field(ge=-100000, le=100000)
    location_id: str = Field(min_length=1, max_length=64)

    @field_validator("qty")
    @classmethod
    def nonzero(cls, v: int) -> int:
        if v == 0:
            raise ValueError("qty must be non-zero")
        return v


class DocumentPayload(BaseModel):
    s3_key: str = Field(min_length=1, max_length=512)
    content_type: Literal["image/jpeg", "image/png", "application/pdf"] = "image/jpeg"
    location_id: str = Field(min_length=1, max_length=64)
    po_number: str | None = None


class Capture(BaseModel):
    model_config = ConfigDict(extra="ignore")

    capture_id: UUID
    site_id: str = Field(min_length=1, max_length=32)
    station_id: str = Field(min_length=1, max_length=64)
    operator_id: str | None = None
    kind: Literal["scan", "document"]
    captured_at: datetime
    payload: dict[str, Any]

    @model_validator(mode="after")
    def check_payload(self) -> Capture:
        if self.kind == "scan":
            ScanPayload.model_validate(self.payload)
        else:
            DocumentPayload.model_validate(self.payload)
        return self

    def scan(self) -> ScanPayload:
        return ScanPayload.model_validate(self.payload)

    def document(self) -> DocumentPayload:
        return DocumentPayload.model_validate(self.payload)


class CaptureRaw(Capture):
    """Value on captures.raw."""

    received_at: datetime
    trace_id: str | None = None


class Field_(BaseModel):
    value: Any = None
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedLineItem(BaseModel):
    line_no: int
    sku: Field_
    part_number: Field_ = Field_(value=None, confidence=0.0)
    qty: Field_
    description: str | None = None


class ExtractionOutput(BaseModel):
    supplier: Field_
    po_number: Field_
    line_items: list[ExtractedLineItem]
    raw_text: str = ""

    def min_confidence(self) -> float:
        confs = [self.supplier.confidence, self.po_number.confidence]
        for li in self.line_items:
            confs += [li.sku.confidence, li.qty.confidence]
        return min(confs) if confs else 0.0


class CorrectedLineItem(BaseModel):
    line_no: int
    sku: str
    qty: int
    location_id: str
    part_number: str | None = None


class ReviewSubmission(BaseModel):
    supplier: str | None = None
    po_number: str | None = None
    line_items: list[CorrectedLineItem]
    notes: str | None = None


ReviewReason = Literal["low_confidence", "audit_sample", "unknown_sku", "extraction_error"]


class ReviewDispatch(BaseModel):
    command_id: str
    extraction_id: UUID
    capture_id: UUID
    reason: ReviewReason
    priority: int = Field(ge=0, le=9)
    min_confidence: float | None = None


class ReorderRequest(BaseModel):
    command_id: str
    sku: str
    on_hand_total: int
    reorder_point: int
    location_id: str | None = None
    requested_at: datetime


class Notify(BaseModel):
    command_id: str
    channel: Literal["log", "sns"] = "log"
    subject: str
    message: str


def review_priority(reason: str, min_confidence: float | None) -> int:
    if reason in ("unknown_sku", "extraction_error"):
        return 0
    if reason == "audit_sample":
        return 9
    return max(0, min(9, round((min_confidence or 0.0) * 9)))
