// Dev-mode identity switcher (AUTH_MODE=dev only): stores {user, groups} in a cookie.
import { NextRequest, NextResponse } from "next/server";
import { config, DEV_IDENTITY_COOKIE } from "@/lib/config";

const ROLES = new Set(["operator", "reviewer", "admin"]);

export async function POST(req: NextRequest) {
  if (config.authMode !== "dev") return NextResponse.json({ error: "forbidden" }, { status: 403 });
  const body = (await req.json()) as { user?: string; groups?: string[] };
  const identity = {
    user: (body.user ?? "dev-user").trim().slice(0, 64) || "dev-user",
    groups: (body.groups ?? []).filter((g) => ROLES.has(g)),
  };
  const res = NextResponse.json(identity);
  res.cookies.set(DEV_IDENTITY_COOKIE, JSON.stringify(identity), { path: "/", sameSite: "lax", httpOnly: true });
  return res;
}
