import "server-only";
import { cookies } from "next/headers";
import { decode } from "next-auth/jwt";
import { config, DEFAULT_DEV_IDENTITY, DEV_IDENTITY_COOKIE } from "./config";

export interface Identity {
  user: string;
  groups: string[];
}

export function devIdentity(): Identity {
  const raw = cookies().get(DEV_IDENTITY_COOKIE)?.value;
  if (!raw) return DEFAULT_DEV_IDENTITY;
  try {
    const parsed = JSON.parse(raw) as Identity;
    return { user: String(parsed.user || DEFAULT_DEV_IDENTITY.user), groups: (parsed.groups ?? []).map(String) };
  } catch {
    return DEFAULT_DEV_IDENTITY;
  }
}

async function idToken(): Promise<string | null> {
  const jar = cookies();
  const raw =
    jar.get("__Secure-next-auth.session-token")?.value ?? jar.get("next-auth.session-token")?.value ?? null;
  if (!raw) return null;
  const token = await decode({ token: raw, secret: process.env.NEXTAUTH_SECRET ?? "" });
  return (token?.idToken as string | undefined) ?? null;
}

/** Headers that authenticate the current user to core-api / ingest. */
export async function authHeaders(): Promise<Record<string, string>> {
  if (config.authMode === "dev") {
    const id = devIdentity();
    return { "x-dev-user": id.user, "x-dev-groups": id.groups.join(",") };
  }
  const token = await idToken();
  return token ? { authorization: `Bearer ${token}` } : {};
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  for (const [k, v] of Object.entries(await authHeaders())) headers.set(k, v);
  return fetch(`${config.apiBaseUrl}/${path.replace(/^\//, "")}`, { ...init, headers, cache: "no-store" });
}
