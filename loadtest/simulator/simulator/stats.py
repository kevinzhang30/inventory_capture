from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(p / 100 * (len(s) - 1))))
    return s[k]


@dataclass
class Stats:
    latencies_ms: list[float] = field(default_factory=list)
    statuses: Counter = field(default_factory=Counter)
    http_errors: Counter = field(default_factory=Counter)
    captures_sent: int = 0
    documents: int = 0

    def summary(self, elapsed_s: float) -> dict[str, float | int | dict]:
        return {
            "captures_sent": self.captures_sent,
            "achieved_rate_per_s": round(self.captures_sent / elapsed_s, 1) if elapsed_s else 0,
            "documents": self.documents,
            "statuses": dict(self.statuses),
            "http_errors": dict(self.http_errors),
            "ack_ms": {f"p{p}": round(percentile(self.latencies_ms, p), 1) for p in (50, 95, 99)},
        }
