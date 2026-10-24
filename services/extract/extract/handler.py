"""extract Lambda (MSK captures.raw): scans → stock movements; documents → LLM extraction + confidence routing."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import psycopg
from botocore.exceptions import ClientError
from pydantic import ValidationError

from extract.extractors import ExtractionError, get_extractor
from extract.extractors.bedrock import TransientModelError
from extract.routing import Route, decide_route, resolve_skus
from inventory_common import app_settings, s3
from inventory_common.db import Conn, transaction
from inventory_common.lambda_events import iter_kafka_records
from inventory_common.log import capture_id_var, emit_metric, get_logger, trace_id_var
from inventory_common.models import CaptureRaw, ExtractionOutput, ReviewDispatch
from inventory_common.stock import (
    MovementIn,
    apply_movements,
    enqueue_command,
    enqueue_event,
    known_locations,
    known_skus,
)

log = get_logger(__name__)
EXTRACT_CONCURRENCY = int(os.environ.get("EXTRACT_CONCURRENCY", "4"))

INSERT_CAPTURE = """
INSERT INTO capture (capture_id, site_id, station_id, operator_id, kind, s3_key, payload, captured_at, received_at)
VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
ON CONFLICT (capture_id) DO NOTHING
"""


def _capture_row(cap: CaptureRaw) -> tuple[Any, ...]:
    return (
        str(cap.capture_id), cap.site_id, cap.station_id, cap.operator_id, cap.kind,
        cap.payload.get("s3_key"), json.dumps(cap.payload), cap.captured_at, cap.received_at,
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    scans: dict[str, CaptureRaw] = {}
    docs: dict[str, CaptureRaw] = {}
    invalid = 0
    for rec in iter_kafka_records(event):
        try:
            cap = CaptureRaw.model_validate(rec.json())
        except (ValidationError, ValueError):
            invalid += 1
            log.error("invalid capture record skipped", extra={"partition": rec.partition, "offset": rec.offset})
            continue
        (scans if cap.kind == "scan" else docs)[str(cap.capture_id)] = cap
    if invalid:
        emit_metric("ExtractInvalidRecords", invalid)
    if scans:
        process_scans(list(scans.values()))
    if docs:
        process_documents(list(docs.values()))
    return {"scans": len(scans), "documents": len(docs), "invalid": invalid}


# ---------------------------------------------------------------- scans

def process_scans(scans: list[CaptureRaw]) -> None:
    ids = [str(c.capture_id) for c in scans]
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.executemany(INSERT_CAPTURE, [_capture_row(c) for c in scans])
        status = {
            str(r["capture_id"]): r["status"]
            for r in conn.execute(
                "SELECT capture_id, status FROM capture WHERE capture_id = ANY(%s::uuid[]) FOR UPDATE", (ids,)
            )
        }
        pending = [c for c in scans if status.get(str(c.capture_id)) == "received"]
        skus = known_skus(conn, [c.scan().sku for c in pending])
        locs = known_locations(conn, [c.scan().location_id for c in pending])
        good: list[CaptureRaw] = []
        for c in pending:
            p = c.scan()
            if p.sku in skus and p.location_id in locs:
                good.append(c)
            else:
                err = "unknown_sku" if p.sku not in skus else "unknown_location"
                conn.execute(
                    "UPDATE capture SET status = 'rejected', error = %s WHERE capture_id = %s", (err, str(c.capture_id))
                )
        # Global (sku, location) order keeps lock acquisition consistent across concurrent invocations.
        good.sort(key=lambda c: (c.scan().sku, c.scan().location_id, str(c.capture_id)))
        for c in good:
            p = c.scan()
            mv = MovementIn(
                sku=p.sku, location_id=p.location_id, qty_delta=p.qty,
                type="receipt" if p.qty > 0 else "issue",
                idempotency_key=f"{c.capture_id}:0", source_capture_id=str(c.capture_id),
            )
            apply_movements(conn, [mv], captured_at=c.captured_at.isoformat())
        if good:
            conn.execute(
                "UPDATE capture SET status = 'applied' WHERE capture_id = ANY(%s::uuid[])",
                ([str(c.capture_id) for c in good],),
            )
    oldest = min(c.received_at for c in scans)
    emit_metric("IngestToApplyLatency", (datetime.now(UTC) - oldest).total_seconds() * 1000, "Milliseconds")
    emit_metric("ScansApplied", len(good))
    if len(pending) - len(good):
        emit_metric("ScansRejected", len(pending) - len(good))


# ---------------------------------------------------------------- documents

def process_documents(docs: list[CaptureRaw]) -> None:
    errors: list[BaseException] = []
    with ThreadPoolExecutor(max_workers=max(1, min(EXTRACT_CONCURRENCY, len(docs)))) as pool:
        for fut in [pool.submit(_process_document_safe, d) for d in docs]:
            exc = fut.result()
            if exc is not None:
                errors.append(exc)
    if errors:
        # Completed documents are committed and idempotent; retrying the batch only redoes the failed ones.
        raise RuntimeError(f"{len(errors)} document(s) failed transiently: {errors[0]!r}") from errors[0]


def _process_document_safe(cap: CaptureRaw) -> BaseException | None:
    capture_id_var.set(str(cap.capture_id))
    trace_id_var.set(cap.trace_id)
    try:
        process_document(cap)
        return None
    except (TransientModelError, psycopg.OperationalError, ClientError) as exc:
        log.warning("transient document failure", exc_info=True)
        return exc


def _load_hints(cap: CaptureRaw, extractor: Any) -> dict[str, Any]:
    doc = cap.document()
    hints: dict[str, Any] = {"po_number": doc.po_number}
    if extractor.model_id == "stub":
        try:
            hints["truth"] = json.loads(s3.get_bytes(f"{doc.s3_key}.truth.json"))
        except ClientError:
            hints["truth"] = None
        if not hints["truth"]:
            with transaction() as conn:
                hints["catalog"] = conn.execute(
                    "SELECT sku, part_number, name, supplier_id FROM part ORDER BY sku LIMIT 200"
                ).fetchall()
    else:
        with transaction() as conn:
            hints["supplier_names"] = [
                f"{r['supplier_id']}: {r['name']}"
                for r in conn.execute("SELECT supplier_id, name FROM supplier ORDER BY supplier_id")
            ]
    return hints


def _run_extraction(cap: CaptureRaw) -> tuple[str, ExtractionOutput | None, str | None]:
    """Returns (extraction_id, output, error). Reuses a stored extraction for the same model+prompt."""
    cid = str(cap.capture_id)
    extractor = get_extractor()
    with transaction() as conn:
        row = conn.execute(
            """SELECT extraction_id, output, error FROM extraction
               WHERE capture_id = %s AND model_id = %s AND prompt_version = %s""",
            (cid, extractor.model_id, extractor.prompt_version),
        ).fetchone()
    if row:
        out = ExtractionOutput.model_validate(row["output"]) if row["output"] else None
        return str(row["extraction_id"]), out, row["error"]

    doc = cap.document()
    output: ExtractionOutput | None = None
    error: str | None = None
    latency = tokens_in = tokens_out = 0
    try:
        image = s3.get_bytes(doc.s3_key) if extractor.needs_image else None
        result = extractor.extract(image, doc.content_type, cid, _load_hints(cap, extractor))
        output, latency = result.output, result.latency_ms
        tokens_in, tokens_out = result.input_tokens, result.output_tokens
        emit_metric("ExtractionLatency", latency, "Milliseconds", {"ModelId": extractor.model_id})
        emit_metric("ExtractionTokens", tokens_in + tokens_out, "Count", {"ModelId": extractor.model_id})
    except ExtractionError as exc:
        error = str(exc)[:1000]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in ("NoSuchKey", "404"):
            raise
        error = f"image not found: {doc.s3_key}"

    with transaction() as conn:
        ins = conn.execute(
            """INSERT INTO extraction (capture_id, model_id, prompt_version, output, min_confidence, latency_ms,
                                       input_tokens, output_tokens, error)
               VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
               ON CONFLICT (capture_id, model_id, prompt_version) DO NOTHING
               RETURNING extraction_id""",
            (cid, extractor.model_id, extractor.prompt_version,
             output.model_dump_json() if output else None,
             round(output.min_confidence(), 4) if output else None,
             latency, tokens_in, tokens_out, error),
        ).fetchone()
        if ins is None:  # a concurrent redelivery won the race; use its result
            return _run_extraction(cap)
    return str(ins["extraction_id"]), output, error


def process_document(cap: CaptureRaw) -> str:
    cid = str(cap.capture_id)
    doc = cap.document()
    with transaction() as conn:
        conn.execute(INSERT_CAPTURE, _capture_row(cap))
        row = conn.execute("SELECT status FROM capture WHERE capture_id = %s", (cid,)).fetchone()
    if row is None or row["status"] != "received":
        return "skipped"

    extraction_id, output, error = _run_extraction(cap)

    with transaction() as conn:
        if output is not None:
            pns = [li.part_number.value for li in output.line_items if not li.sku.value and li.part_number.value]
            mapping = {}
            if pns:
                mapping = {
                    r["part_number"]: r["sku"]
                    for r in conn.execute("SELECT part_number, sku FROM part WHERE part_number = ANY(%s)", (pns,))
                }
            output = resolve_skus(output, mapping)
        skus = known_skus(conn, [li.sku.value for li in output.line_items if li.sku.value] if output else [])
        route = decide_route(
            capture_id=cid, output=output, error=error, known_skus=skus,
            location_known=bool(known_locations(conn, [doc.location_id])),
            threshold=app_settings.confidence_threshold(), audit_rate=app_settings.audit_sample_rate(),
        )
        new_status = "applied" if route.action == "apply" else "pending_review"
        moved = conn.execute(
            "UPDATE capture SET status = %s WHERE capture_id = %s AND status = 'received' RETURNING capture_id",
            (new_status, cid),
        ).fetchone()
        if moved is None:
            return "skipped"
        if route.action == "apply" and output is not None:
            apply_movements(
                conn,
                [
                    MovementIn(
                        sku=li.sku.value, location_id=doc.location_id, qty_delta=int(li.qty.value),
                        type="receipt", idempotency_key=f"{cid}:{li.line_no}", source_capture_id=cid,
                    )
                    for li in output.line_items
                ],
                captured_at=cap.captured_at.isoformat(),
            )
        else:
            _dispatch_review(conn, cid, extraction_id, route, output)
        enqueue_event(conn, cid, _document_event(cap, extraction_id, output,
                                                 "auto_applied" if route.action == "apply" else "pending_review"))
    emit_metric("DocumentsRouted", 1, "Count", {"Route": route.reason or "auto_applied"})
    return new_status


def _dispatch_review(
    conn: Conn, cid: str, extraction_id: str, route: Route, output: ExtractionOutput | None
) -> None:
    cmd = ReviewDispatch(
        command_id=f"review:{extraction_id}",
        extraction_id=extraction_id,  # type: ignore[arg-type]
        capture_id=cid,  # type: ignore[arg-type]
        reason=route.reason,  # type: ignore[arg-type]
        priority=route.priority or 0,
        min_confidence=round(output.min_confidence(), 4) if output else None,
    )
    enqueue_command(conn, "review.dispatch", cmd.model_dump(mode="json"))


def _document_event(
    cap: CaptureRaw, extraction_id: str, output: ExtractionOutput | None, status: str
) -> dict[str, Any]:
    return {
        "type": "document.extracted",
        "capture_id": str(cap.capture_id),
        "extraction_id": extraction_id,
        "site_id": cap.site_id,
        "supplier": output.supplier.value if output else None,
        "po_number": output.po_number.value if output else None,
        "raw_text": output.raw_text if output else "",
        "line_items": [
            {"line_no": li.line_no, "sku": li.sku.value, "part_number": li.part_number.value,
             "qty": li.qty.value, "description": li.description}
            for li in (output.line_items if output else [])
        ],
        "status": status,
        "captured_at": cap.captured_at.isoformat(),
    }
