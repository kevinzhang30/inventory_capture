// Browser → this route → core-api / ingest. Auth is attached here so tokens never reach client JS.
import { NextRequest, NextResponse } from "next/server";
import { apiFetch } from "@/lib/api";

const ALLOWED = new Set(["stock", "parts", "search", "dashboard", "captures", "reviews", "eval", "me", "admin"]);

export const dynamic = "force-dynamic";

async function forward(req: NextRequest, { params }: { params: { path: string[] } }) {
  const [head] = params.path;
  if (!head || !ALLOWED.has(head)) {
    return NextResponse.json({ error: "not_found", detail: "unknown API path" }, { status: 404 });
  }
  const path = params.path.map(encodeURIComponent).join("/") + req.nextUrl.search;
  const body = req.method === "GET" ? undefined : await req.text();
  const upstream = await apiFetch(path, {
    method: req.method,
    body,
    headers: body ? { "content-type": req.headers.get("content-type") ?? "application/json" } : undefined,
  });
  if (upstream.status === 204) return new NextResponse(null, { status: 204 });
  return new NextResponse(await upstream.text(), {
    status: upstream.status,
    headers: { "content-type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

export { forward as GET, forward as POST, forward as PUT };
