"""eval-nightly Lambda (EventBridge Scheduler) / CLI: accuracy + calibration per (model_id, prompt_version).

    python -m eval_nightly.handler [--since-days 30] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from eval_nightly.metrics import compute_metrics
from inventory_common import app_settings
from inventory_common.config import settings
from inventory_common.db import connection, transaction
from inventory_common.log import emit_metric, get_logger

log = get_logger(__name__)

TARGET_PRECISION = float(os.environ.get("EVAL_TARGET_PRECISION", "0.98"))
MIN_SAMPLES = int(os.environ.get("EVAL_MIN_SAMPLES", "50"))
AUTO_TUNE = os.environ.get("AUTO_TUNE_THRESHOLD", "false").lower() == "true"


def load_pairs(since_days: int) -> dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]]:
    groups: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    with connection() as conn:
        rows = conn.execute(
            """SELECT e.model_id, e.prompt_version, e.output, gt.corrected
               FROM extraction e JOIN ground_truth gt ON gt.extraction_id = e.extraction_id
               WHERE e.output IS NOT NULL AND gt.created_at > now() - make_interval(days => %s)""",
            (since_days,),
        ).fetchall()
        conn.rollback()
    for r in rows:
        groups.setdefault((r["model_id"], r["prompt_version"]), []).append((r["output"], r["corrected"]))
    return groups


def production_key() -> tuple[str, str]:
    model = "stub" if settings.extractor == "stub" else settings.bedrock_model_id
    return model, settings.prompt_version


def run(since_days: int = 30, dry_run: bool = False) -> list[dict[str, Any]]:
    results = []
    for (model_id, prompt_version), pairs in load_pairs(since_days).items():
        metrics = compute_metrics(pairs, TARGET_PRECISION, MIN_SAMPLES)
        results.append({"model_id": model_id, "prompt_version": prompt_version, "metrics": metrics})
        dims = {"ModelId": model_id, "PromptVersion": prompt_version}
        if metrics["document_exact_match"] is not None:
            emit_metric("EvalDocumentExactMatch", metrics["document_exact_match"], "None", dims)
        if dry_run:
            continue
        with transaction() as conn:
            conn.execute(
                """INSERT INTO eval_run (kind, model_id, prompt_version, sample_size, metrics)
                   VALUES ('nightly', %s, %s, %s, %s::jsonb)""",
                (model_id, prompt_version, len(pairs), json.dumps(metrics)),
            )
            threshold = metrics["recommended_threshold"]
            if AUTO_TUNE and threshold is not None and (model_id, prompt_version) == production_key():
                conn.execute(
                    """INSERT INTO app_setting (key, value) VALUES ('confidence_threshold', %s::jsonb)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
                    (json.dumps(threshold),),
                )
                log.info("auto-tuned confidence threshold", extra={"threshold": threshold, "model_id": model_id})
        if AUTO_TUNE:
            app_settings.invalidate("confidence_threshold")
    return results


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    results = run(int((event or {}).get("since_days", 30)))
    return {"groups": len(results), "results": [
        {k: r[k] for k in ("model_id", "prompt_version")} | {"n": r["metrics"]["n_extractions"]} for r in results
    ]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(args.since_days, args.dry_run), indent=2, default=str))
