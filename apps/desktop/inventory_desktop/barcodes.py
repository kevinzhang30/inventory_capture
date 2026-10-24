"""Barcode classification and the scan-sequence state machine (UI-free, unit-tested).

Conventions (printed on bin labels and item labels):
  LOC:<location_id>  or a bare location id like DAL1-A01-01 / DAL1-RECV-01  → location
  QTY:<n>                                                                     → quantity
  SKU-NNNNNN or anything else                                                 → item
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LOCATION_RE = re.compile(r"^[A-Z0-9]{3,8}-(?:[A-Z]\d{2}-\d{2}|RECV-\d{2}|STAGE-\d{2})$")
QTY_RE = re.compile(r"^QTY:(-?\d{1,6})$")


@dataclass(frozen=True)
class Code:
    kind: str  # location | qty | item
    value: str


def classify(raw: str) -> Code:
    s = raw.strip().upper()
    if s.startswith("LOC:"):
        return Code("location", s[4:])
    if m := QTY_RE.match(s):
        return Code("qty", m.group(1))
    if LOCATION_RE.match(s):
        return Code("location", s)
    return Code("item", s)


@dataclass
class ScanSession:
    """Location sticks until another location is scanned; quantity resets to 1 after each item."""

    location_id: str | None = None
    qty: int = 1
    default_qty: int = 1
    committed: list[tuple[str, int, str]] = field(default_factory=list)

    def feed(self, raw: str) -> tuple[str, int, str] | str:
        """Returns a committed (sku, qty, location_id) or a status message for the UI."""
        code = classify(raw)
        if not code.value:
            return "empty scan ignored"
        if code.kind == "location":
            self.location_id = code.value
            return f"location set to {code.value}"
        if code.kind == "qty":
            q = int(code.value)
            if q == 0:
                return "quantity must be non-zero"
            self.qty = q
            return f"quantity set to {q}"
        if self.location_id is None:
            return "scan a bin/location label first"
        item = (code.value, self.qty, self.location_id)
        self.committed.append(item)
        self.qty = self.default_qty
        return item
