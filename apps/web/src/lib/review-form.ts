// Review workspace form model: extraction output -> editable form -> submission body.
import type { ReviewSubmission, ReviewTask } from "./types";

export interface FormLine {
  key: string;
  line_no: number;
  sku: string;
  qty: string;
  location_id: string;
  part_number: string;
  description: string;
  confidence: { sku: number | null; qty: number | null };
}

export interface ReviewForm {
  supplier: string;
  po_number: string;
  supplier_confidence: number | null;
  po_confidence: number | null;
  line_items: FormLine[];
  notes: string;
}

let counter = 0;
export const newKey = () => `l${Date.now().toString(36)}${(counter++).toString(36)}`;

export function formFromTask(task: ReviewTask): ReviewForm {
  const out = task.extraction.output;
  const location = task.capture.payload.location_id ?? "";
  return {
    supplier: out?.supplier.value ?? "",
    po_number: out?.po_number.value ?? task.capture.payload.po_number ?? "",
    supplier_confidence: out?.supplier.confidence ?? null,
    po_confidence: out?.po_number.confidence ?? null,
    notes: "",
    line_items: (out?.line_items ?? []).map((li) => ({
      key: newKey(),
      line_no: li.line_no,
      sku: li.sku.value ?? "",
      qty: li.qty.value === null || li.qty.value === undefined ? "" : String(li.qty.value),
      location_id: location,
      part_number: li.part_number?.value ?? "",
      description: li.description ?? "",
      confidence: { sku: li.sku.confidence, qty: li.qty.confidence },
    })),
  };
}

export function blankLine(form: ReviewForm, location: string): FormLine {
  const next = form.line_items.reduce((m, l) => Math.max(m, l.line_no), 0) + 1;
  return {
    key: newKey(), line_no: next, sku: "", qty: "1", location_id: location, part_number: "", description: "",
    confidence: { sku: null, qty: null },
  };
}

export interface FormError {
  line_no: number | null;
  field: string;
  error: string;
}

export function validateForm(form: ReviewForm): FormError[] {
  const errors: FormError[] = [];
  if (form.line_items.length === 0) errors.push({ line_no: null, field: "line_items", error: "add at least one line" });
  const seen = new Set<number>();
  for (const l of form.line_items) {
    if (!l.sku.trim()) errors.push({ line_no: l.line_no, field: "sku", error: "required" });
    if (!l.location_id.trim()) errors.push({ line_no: l.line_no, field: "location_id", error: "required" });
    const q = Number(l.qty);
    if (!Number.isInteger(q) || q <= 0) errors.push({ line_no: l.line_no, field: "qty", error: "positive integer" });
    if (seen.has(l.line_no)) errors.push({ line_no: l.line_no, field: "line_no", error: "duplicate line" });
    seen.add(l.line_no);
  }
  return errors;
}

export function toSubmission(form: ReviewForm): ReviewSubmission {
  return {
    supplier: form.supplier.trim() || null,
    po_number: form.po_number.trim() || null,
    notes: form.notes.trim() || undefined,
    line_items: form.line_items.map((l) => ({
      line_no: l.line_no,
      sku: l.sku.trim().toUpperCase(),
      qty: Number(l.qty),
      location_id: l.location_id.trim().toUpperCase(),
      part_number: l.part_number.trim() || null,
    })),
  };
}

/** Maps a 422 response from core-api ({error, detail: [{line_no, field, error}]}) onto form errors. */
export function serverErrors(detail: unknown): FormError[] {
  if (!Array.isArray(detail)) return [{ line_no: null, field: "form", error: String(detail ?? "invalid") }];
  return detail.map((d) => ({
    line_no: typeof d?.line_no === "number" ? d.line_no : null,
    field: String(d?.field ?? d?.loc?.join(".") ?? "form"),
    error: String(d?.error ?? d?.msg ?? "invalid"),
  }));
}
