"""Structured JSON logging with capture_id / trace_id context, plus CloudWatch EMF metrics."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from typing import Any

from inventory_common.config import settings

capture_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("capture_id", default=None)
trace_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)

_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if (cid := capture_id_var.get()) is not None:
            out["capture_id"] = cid
        if (tid := trace_id_var.get()) is not None:
            out["trace_id"] = tid
        for k, v in record.__dict__.items():
            if k not in _RESERVED and not k.startswith("_"):
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


_configured = False


def get_logger(name: str) -> logging.Logger:
    global _configured
    if not _configured:
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
        root.setLevel(settings.log_level)
        for noisy in ("botocore", "urllib3", "pika", "opensearch", "kafka"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _configured = True
    return logging.getLogger(name)


def emit_metric(
    name: str,
    value: float,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
    namespace: str = "InventoryCapture",
) -> None:
    """Write a CloudWatch Embedded Metric Format line to stdout (no-op cost locally)."""
    dims = dimensions or {}
    doc: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": namespace,
                    "Dimensions": [list(dims.keys())] if dims else [[]],
                    "Metrics": [{"Name": name, "Unit": unit}],
                }
            ],
        },
        name: value,
        **dims,
    }
    sys.stdout.write(json.dumps(doc) + "\n")
