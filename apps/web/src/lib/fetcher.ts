// Browser-side fetch helpers. All requests go through /api/proxy (auth is attached server-side).
import type { ApiErrorBody } from "./types";

export class HttpError extends Error {
  constructor(public status: number, public body: ApiErrorBody | null) {
    super(body?.error ?? `HTTP ${status}`);
  }
}

export const proxy = (path: string) => `/api/proxy/${path.replace(/^\//, "")}`;

async function handle<T>(res: Response): Promise<T> {
  if (res.status === 204) return null as T;
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) throw new HttpError(res.status, body);
  return body as T;
}

export async function fetcher<T>(path: string): Promise<T> {
  return handle<T>(await fetch(proxy(path), { cache: "no-store" }));
}

export async function send<T>(method: "POST" | "PUT", path: string, body?: unknown): Promise<T> {
  return handle<T>(
    await fetch(proxy(path), {
      method,
      headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  );
}
