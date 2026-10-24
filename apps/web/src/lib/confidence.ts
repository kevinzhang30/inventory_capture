export type ConfidenceLevel = "low" | "medium" | "high" | "unknown";

export const LOW_BELOW = 0.7;
export const MEDIUM_BELOW = 0.85;

export function confidenceLevel(c: number | null | undefined): ConfidenceLevel {
  if (c === null || c === undefined || Number.isNaN(c)) return "unknown";
  if (c < LOW_BELOW) return "low";
  if (c < MEDIUM_BELOW) return "medium";
  return "high";
}

export function pct(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}
