"""Extraction accuracy and calibration metrics (docs/CONTRACTS.md §9). Pure functions over plain dicts.

`output` is an ExtractionOutput dict (values + confidences); `truth` is a ground-truth dict
({"supplier", "po_number", "line_items": [{"line_no", "sku", "qty", ...}]}).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

N_BINS = 10


def _norm(v: Any) -> Any:
    return v.strip().upper() if isinstance(v, str) else v


def _eq(a: Any, b: Any) -> bool:
    return a is not None and _norm(a) == _norm(b)


@dataclass
class DocScore:
    supplier_ok: bool
    po_ok: bool
    sku_tp: int
    sku_pred: int
    sku_truth: int
    qty_ok: int
    qty_matched: int
    items_exact: int
    items_truth: int
    stock_correct: bool  # every line's sku+qty right and no extra lines — what auto-apply needs
    doc_exact: bool
    min_confidence: float
    field_conf: list[tuple[float, bool]]


Item = dict[str, Any]


def _match_items(pred: list[Item], truth: list[Item]) -> list[tuple[Item, Item]]:
    """Pair predicted and true lines by line_no; unpaired lines fall back to matching by SKU."""
    by_no = {t["line_no"]: t for t in truth}
    pairs, used, left = [], set(), []
    for p in pred:
        t = by_no.get(p["line_no"])
        if t is not None and t["line_no"] not in used:
            pairs.append((p, t))
            used.add(t["line_no"])
        else:
            left.append(p)
    for p in left:
        for t in truth:
            if t["line_no"] not in used and _eq((p.get("sku") or {}).get("value"), t.get("sku")):
                pairs.append((p, t))
                used.add(t["line_no"])
                break
    return pairs


def score_document(output: dict[str, Any], truth: dict[str, Any]) -> DocScore:
    pred_items = output.get("line_items") or []
    true_items = truth.get("line_items") or []
    sup, po = output.get("supplier") or {}, output.get("po_number") or {}
    supplier_ok = _eq(sup.get("value"), truth.get("supplier"))
    po_ok = _eq(po.get("value"), truth.get("po_number"))
    field_conf = [(float(sup.get("confidence", 0)), supplier_ok), (float(po.get("confidence", 0)), po_ok)]
    confs = [float(sup.get("confidence", 0)), float(po.get("confidence", 0))]

    pairs = _match_items(pred_items, true_items)
    paired_pred = {id(p) for p, _ in pairs}
    sku_tp = qty_ok = exact = 0
    for p, t in pairs:
        s_ok = _eq((p.get("sku") or {}).get("value"), t.get("sku"))
        q_ok = (p.get("qty") or {}).get("value") == t.get("qty")
        sku_tp += s_ok
        qty_ok += q_ok
        exact += s_ok and q_ok
        field_conf += [(float(p["sku"].get("confidence", 0)), s_ok), (float(p["qty"].get("confidence", 0)), q_ok)]
    for p in pred_items:
        confs += [float((p.get("sku") or {}).get("confidence", 0)), float((p.get("qty") or {}).get("confidence", 0))]
        if id(p) not in paired_pred:
            field_conf += [(float((p.get("sku") or {}).get("confidence", 0)), False),
                           (float((p.get("qty") or {}).get("confidence", 0)), False)]
    sku_pred = sum(1 for p in pred_items if (p.get("sku") or {}).get("value"))
    stock_correct = exact == len(true_items) == len(pred_items)
    return DocScore(
        supplier_ok=supplier_ok, po_ok=po_ok, sku_tp=sku_tp, sku_pred=sku_pred, sku_truth=len(true_items),
        qty_ok=qty_ok, qty_matched=len(pairs), items_exact=exact, items_truth=len(true_items),
        stock_correct=stock_correct, doc_exact=stock_correct and supplier_ok and po_ok,
        min_confidence=min(confs) if confs else 0.0, field_conf=field_conf,
    )


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def calibration(
    field_conf: list[tuple[float, bool]], n_bins: int = N_BINS
) -> tuple[list[dict[str, Any]], float | None]:
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
    for conf, ok in field_conf:
        bins[min(int(conf * n_bins), n_bins - 1)].append((conf, ok))
    total = len(field_conf)
    out, ece = [], 0.0
    for i, b in enumerate(bins):
        mean_c = sum(c for c, _ in b) / len(b) if b else None
        acc = sum(ok for _, ok in b) / len(b) if b else None
        out.append({"bin_lo": round(i / n_bins, 2), "bin_hi": round((i + 1) / n_bins, 2), "count": len(b),
                    "mean_confidence": round(mean_c, 4) if mean_c is not None else None,
                    "accuracy": round(acc, 4) if acc is not None else None})
        if b:
            ece += len(b) / total * abs(acc - mean_c)  # type: ignore[operator]
    return out, (round(ece, 4) if total else None)


def recommend_threshold(docs: list[DocScore], target_precision: float, min_samples: int,
                        min_selected: int = 10) -> float | None:
    """Lowest threshold t such that docs with min_confidence >= t are stock-correct at >= target precision."""
    if len(docs) < min_samples:
        return None
    for step in range(50, 100):
        t = step / 100
        sel = [d for d in docs if d.min_confidence >= t]
        if len(sel) < min_selected:
            return None
        if sum(d.stock_correct for d in sel) / len(sel) >= target_precision:
            return t
    return None


def compute_metrics(pairs: list[tuple[dict[str, Any], dict[str, Any]]], target_precision: float = 0.98,
                    min_samples: int = 50) -> dict[str, Any]:
    docs = [score_document(o, t) for o, t in pairs]
    n = len(docs)
    sku_tp = sum(d.sku_tp for d in docs)
    sku_pred = sum(d.sku_pred for d in docs)
    sku_truth = sum(d.sku_truth for d in docs)
    precision, recall = _ratio(sku_tp, sku_pred), _ratio(sku_tp, sku_truth)
    f1 = round(2 * precision * recall / (precision + recall), 4) if precision and recall else 0.0 if n else None
    cal, ece = calibration([fc for d in docs for fc in d.field_conf])
    return {
        "n_extractions": n,
        "n_line_items": sku_truth,
        "fields": {
            "supplier": {"accuracy": _ratio(sum(d.supplier_ok for d in docs), n)},
            "po_number": {"accuracy": _ratio(sum(d.po_ok for d in docs), n)},
            "sku": {"precision": precision, "recall": recall, "f1": f1},
            "qty": {"accuracy": _ratio(sum(d.qty_ok for d in docs), sum(d.qty_matched for d in docs))},
        },
        "line_item_exact_match": _ratio(sum(d.items_exact for d in docs), sku_truth),
        "document_exact_match": _ratio(sum(d.doc_exact for d in docs), n),
        "calibration": cal,
        "ece": ece,
        "recommended_threshold": recommend_threshold(docs, target_precision, min_samples),
        "target_precision": target_precision,
    }
