"""Run an extractor over the golden set and report accuracy/calibration before promoting a prompt or model.

    python -m evalkit.run --extractor bedrock --model-id <id> --prompt-version v1 --golden eval/golden \
        [--limit 50] [--save-db] [--report eval/reports/<ts>.md]
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval_nightly.metrics import compute_metrics
from extract.extractors import ExtractionError, get_extractor

CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".pdf": "application/pdf"}


def load_golden(golden: Path, limit: int | None = None) -> list[tuple[Path, dict[str, Any]]]:
    items = []
    for truth_path in sorted(golden.glob("*.truth.json")):
        stem = truth_path.name[: -len(".truth.json")]
        image = next((golden / f"{stem}{ext}" for ext in CONTENT_TYPES if (golden / f"{stem}{ext}").exists()), None)
        if image is not None:
            items.append((image, json.loads(truth_path.read_text())))
    return items[:limit] if limit else items


def evaluate(extractor: Any, items: list[tuple[Path, dict[str, Any]]], concurrency: int = 4) -> dict[str, Any]:
    def one(item: tuple[Path, dict[str, Any]]) -> dict[str, Any]:
        image, truth = item
        hints = {"truth": truth} if extractor.model_id == "stub" else {}
        try:
            res = extractor.extract(image.read_bytes(), CONTENT_TYPES[image.suffix.lower()], image.stem, hints)
            return {"output": res.output.model_dump(mode="json"), "truth": truth, "latency_ms": res.latency_ms,
                    "tokens": res.input_tokens + res.output_tokens}
        except ExtractionError as exc:
            return {"error": str(exc), "truth": truth}

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(one, items))
    ok = [r for r in results if "output" in r]
    metrics = compute_metrics([(r["output"], r["truth"]) for r in ok], min_samples=1)
    latencies = sorted(r["latency_ms"] for r in ok)
    metrics["errors"] = len(results) - len(ok)
    metrics["latency_ms_p50"] = latencies[len(latencies) // 2] if latencies else None
    metrics["total_tokens"] = sum(r["tokens"] for r in ok)
    metrics["wall_s"] = round(time.monotonic() - started, 1)
    return metrics


def render_report(model_id: str, prompt_version: str, n: int, m: dict[str, Any]) -> str:
    f = m["fields"]
    lines = [
        f"# Golden-set eval — {model_id} / prompt {prompt_version}",
        "",
        f"Run at {datetime.now(UTC):%Y-%m-%d %H:%M UTC} over {n} slips ({m['errors']} extraction errors).",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Supplier accuracy | {f['supplier']['accuracy']} |",
        f"| PO accuracy | {f['po_number']['accuracy']} |",
        f"| SKU precision / recall / F1 | {f['sku']['precision']} / {f['sku']['recall']} / {f['sku']['f1']} |",
        f"| Qty accuracy | {f['qty']['accuracy']} |",
        f"| Line-item exact match | {m['line_item_exact_match']} |",
        f"| Document exact match | {m['document_exact_match']} |",
        f"| ECE | {m['ece']} |",
        f"| Recommended threshold (precision ≥ {m['target_precision']}) | {m['recommended_threshold']} |",
        f"| Latency p50 (ms) | {m['latency_ms_p50']} |",
        f"| Total tokens | {m['total_tokens']} |",
        "",
        "## Calibration",
        "",
        "| Confidence bin | Count | Mean confidence | Accuracy |",
        "| --- | --- | --- | --- |",
    ]
    lines += [f"| {b['bin_lo']:.1f}–{b['bin_hi']:.1f} | {b['count']} | {b['mean_confidence']} | {b['accuracy']} |"
              for b in m["calibration"] if b["count"]]
    return "\n".join(lines) + "\n"


def save_db(model_id: str, prompt_version: str, n: int, metrics: dict[str, Any]) -> None:
    from inventory_common.db import transaction

    with transaction() as conn:
        conn.execute(
            """INSERT INTO eval_run (kind, model_id, prompt_version, sample_size, metrics)
               VALUES ('golden', %s, %s, %s, %s::jsonb)""",
            (model_id, prompt_version, n, json.dumps(metrics)),
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", choices=["stub", "bedrock"], default="stub")
    ap.add_argument("--model-id")
    ap.add_argument("--prompt-version", default="v1")
    ap.add_argument("--golden", type=Path, default=Path("eval/golden"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--save-db", action="store_true")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    items = load_golden(args.golden, args.limit)
    if not items:
        raise SystemExit(f"no golden items in {args.golden}; run `python -m evalkit.generate_golden` first")
    extractor = get_extractor(args.extractor, args.model_id, args.prompt_version)
    metrics = evaluate(extractor, items, args.concurrency)
    report = render_report(extractor.model_id, extractor.prompt_version, len(items), metrics)
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report)
    if args.save_db:
        save_db(extractor.model_id, extractor.prompt_version, len(items), metrics)


if __name__ == "__main__":
    main()
