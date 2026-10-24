"""Client-generated UUIDv7 capture IDs (ADR-004): retries are idempotent end to end."""

from __future__ import annotations

import uuid6


def new_capture_id() -> str:
    return str(uuid6.uuid7())
