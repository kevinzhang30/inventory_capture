import { describe, expect, it } from "vitest";
import { blankLine, formFromTask, serverErrors, toSubmission, validateForm } from "./review-form";
import type { ReviewTask } from "./types";

const f = <T,>(value: T | null, confidence = 0.9) => ({ value, confidence });

const task: ReviewTask = {
  task_id: "t1", extraction_id: "e1", capture_id: "c1", reason: "low_confidence", priority: 5, status: "claimed",
  claimed_by: "u", lease_expires_at: null, image_url: null,
  capture: { site_id: "DAL1", station_id: "S1", captured_at: "2026-10-22T10:00:00Z", payload: { location_id: "DAL1-RECV-01" } },
  extraction: {
    model_id: "stub", prompt_version: "v1", min_confidence: 0.4,
    output: {
      supplier: f("SUP-ACME"), po_number: f("PO-1", 0.4), raw_text: "",
      line_items: [{ line_no: 1, sku: f("SKU-000001", 0.5), part_number: f("ACME-1"), qty: f(5) }],
    },
  },
};

describe("review form", () => {
  it("prefills from the extraction and the capture location", () => {
    const form = formFromTask(task);
    expect(form.supplier).toBe("SUP-ACME");
    expect(form.line_items[0]).toMatchObject({ sku: "SKU-000001", qty: "5", location_id: "DAL1-RECV-01" });
    expect(form.line_items[0]?.confidence).toEqual({ sku: 0.5, qty: 0.9 });
  });

  it("maps to a submission with normalised values", () => {
    const form = formFromTask(task);
    form.line_items[0]!.sku = " sku-000002 ";
    form.line_items.push({ ...blankLine(form, "dal1-a01-01"), sku: "SKU-000003", qty: "2" });
    const sub = toSubmission(form);
    expect(sub.line_items).toEqual([
      { line_no: 1, sku: "SKU-000002", qty: 5, location_id: "DAL1-RECV-01", part_number: "ACME-1" },
      { line_no: 2, sku: "SKU-000003", qty: 2, location_id: "DAL1-A01-01", part_number: null },
    ]);
    expect(sub.notes).toBeUndefined();
  });

  it("validates lines", () => {
    const form = formFromTask(task);
    form.line_items[0]!.qty = "0";
    form.line_items[0]!.sku = "";
    expect(validateForm(form).map((e) => e.field).sort()).toEqual(["qty", "sku"]);
    expect(validateForm({ ...form, line_items: [] })[0]?.field).toBe("line_items");
  });

  it("maps server 422 details", () => {
    expect(serverErrors([{ line_no: 1, field: "sku", error: "unknown sku" }])).toEqual([
      { line_no: 1, field: "sku", error: "unknown sku" },
    ]);
    expect(serverErrors("bad")[0]?.field).toBe("form");
  });
});
