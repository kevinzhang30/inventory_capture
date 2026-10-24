// Wire types mirroring docs/CONTRACTS.md §2, §3, §9.

export interface Me {
  user_id: string;
  email: string | null;
  groups: string[];
}

export interface StockLocation {
  location_id: string;
  on_hand: number;
  version: number;
}

export interface Stock {
  sku: string;
  on_hand_total: number;
  locations: StockLocation[];
  source: "cache" | "db";
}

export interface Part {
  sku: string;
  part_number: string;
  name: string;
  category: string;
  supplier_id: string | null;
  supplier_name: string | null;
  uom: string;
  reorder_point: number;
  updated_at?: string;
}

export interface PartDetail extends Part {
  stock: Stock;
}

export interface PartDoc extends Part {
  on_hand_total?: number;
  sites?: string[];
  locations?: (StockLocation & { site_id: string })[];
  score?: number;
}

export interface DocLineItem {
  line_no: number;
  sku: string | null;
  part_number: string | null;
  qty: number | null;
  description: string | null;
}

export interface DocumentDoc {
  capture_id: string;
  extraction_id: string;
  site_id: string;
  supplier: string | null;
  po_number: string | null;
  raw_text: string;
  status: "auto_applied" | "pending_review" | "reviewed";
  captured_at: string;
  line_items: DocLineItem[];
}

export interface Facet {
  key: string;
  count: number;
}

export interface SearchResult<T> {
  total: number;
  items: T[];
  facets: Record<string, Facet[]>;
}

export interface Movement {
  movement_id: number;
  sku: string;
  location_id: string;
  qty_delta: number;
  type: string;
  created_at: string;
}

export interface DashboardSummary {
  captures_last_hour: number;
  pending_reviews: number;
  claimed_reviews: number;
  low_stock: { sku: string; name: string; on_hand_total: number; reorder_point: number }[];
  recent_movements: Movement[];
}

export interface Field<T> {
  value: T | null;
  confidence: number;
}

export interface ExtractedLineItem {
  line_no: number;
  sku: Field<string>;
  part_number: Field<string>;
  qty: Field<number>;
  description?: string | null;
}

export interface ExtractionOutput {
  supplier: Field<string>;
  po_number: Field<string>;
  line_items: ExtractedLineItem[];
  raw_text: string;
}

export type ReviewReason = "low_confidence" | "audit_sample" | "unknown_sku" | "extraction_error";

export interface ReviewTask {
  task_id: string;
  extraction_id: string;
  capture_id: string;
  reason: ReviewReason;
  priority: number;
  status: "ready" | "claimed" | "done";
  claimed_by: string | null;
  lease_expires_at: string | null;
  image_url: string | null;
  capture: {
    site_id: string;
    station_id: string;
    captured_at: string;
    payload: { location_id?: string; po_number?: string; content_type?: string; s3_key?: string };
  };
  extraction: {
    model_id: string;
    prompt_version: string;
    min_confidence: number | null;
    output: ExtractionOutput | null;
  };
}

export interface ReviewStats {
  ready: number;
  claimed: number;
  done_today: number;
}

export interface CorrectedLineItem {
  line_no: number;
  sku: string;
  qty: number;
  location_id: string;
  part_number?: string | null;
}

export interface ReviewSubmission {
  supplier: string | null;
  po_number: string | null;
  line_items: CorrectedLineItem[];
  notes?: string;
}

export interface CaptureDetail {
  capture: {
    capture_id: string;
    site_id: string;
    station_id: string;
    operator_id: string | null;
    kind: "scan" | "document";
    status: string;
    payload: Record<string, unknown>;
    captured_at: string;
    received_at: string;
    error: string | null;
  };
  extractions: {
    extraction_id: string;
    model_id: string;
    prompt_version: string;
    output: ExtractionOutput | null;
    min_confidence: number | null;
    latency_ms: number | null;
    input_tokens: number | null;
    output_tokens: number | null;
    error: string | null;
    created_at: string;
    ground_truth: ReviewSubmission | null;
    reviewer_id: string | null;
    task_id: string | null;
    review_status: string | null;
    reason: string | null;
  }[];
  movements: Movement[];
  image_url: string | null;
}

export interface CalibrationBin {
  bin_lo: number;
  bin_hi: number;
  count: number;
  mean_confidence: number | null;
  accuracy: number | null;
}

export interface EvalMetrics {
  n_extractions: number;
  n_line_items: number;
  fields: {
    supplier: { accuracy: number | null };
    po_number: { accuracy: number | null };
    sku: { precision: number | null; recall: number | null; f1: number | null };
    qty: { accuracy: number | null };
  };
  line_item_exact_match: number | null;
  document_exact_match: number | null;
  calibration: CalibrationBin[];
  ece: number | null;
  recommended_threshold: number | null;
  target_precision: number;
}

export interface EvalRun {
  run_id: string;
  kind: "nightly" | "golden";
  model_id: string;
  prompt_version: string;
  sample_size: number;
  metrics: EvalMetrics;
  created_at: string;
}

export interface ApiErrorBody {
  error: string;
  detail: unknown;
}
