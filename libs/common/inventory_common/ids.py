"""UUIDv7 helpers (time-ordered, client-generated capture IDs — ADR-004)."""

from __future__ import annotations

import uuid

import uuid6


def uuid7() -> uuid.UUID:
    return uuid.UUID(str(uuid6.uuid7()))


def uuid7_str() -> str:
    return str(uuid7())
