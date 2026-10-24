// Search page state <-> URL query string.

export interface PartsQuery {
  q: string;
  category: string[];
  supplier: string[];
  site: string[];
  page: number;
}

export interface DocumentsQuery {
  q: string;
  supplier: string[];
  from: string;
  to: string;
  page: number;
}

function list(params: URLSearchParams, key: string): string[] {
  return params.getAll(key).filter(Boolean);
}

function page(params: URLSearchParams): number {
  const n = Number.parseInt(params.get("page") ?? "1", 10);
  return Number.isFinite(n) && n > 0 ? n : 1;
}

export function parsePartsQuery(params: URLSearchParams): PartsQuery {
  return {
    q: params.get("q") ?? "",
    category: list(params, "category"),
    supplier: list(params, "supplier"),
    site: list(params, "site"),
    page: page(params),
  };
}

export function parseDocumentsQuery(params: URLSearchParams): DocumentsQuery {
  return {
    q: params.get("q") ?? "",
    supplier: list(params, "supplier"),
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    page: page(params),
  };
}

export function toSearchParams(state: Record<string, string | string[] | number | undefined>): URLSearchParams {
  const out = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) {
    if (v === undefined || v === "" || (k === "page" && v === 1)) continue;
    if (Array.isArray(v)) v.forEach((x) => out.append(k, x));
    else out.set(k, String(v));
  }
  return out;
}

export function toggle(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}
