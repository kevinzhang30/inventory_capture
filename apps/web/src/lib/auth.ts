import "server-only";
import type { NextAuthOptions } from "next-auth";
import type { JWT } from "next-auth/jwt";
import CognitoProvider from "next-auth/providers/cognito";
import { config } from "./config";

export function decodeJwtPayload(token: string): Record<string, unknown> {
  const part = token.split(".")[1] ?? "";
  return JSON.parse(Buffer.from(part.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"));
}

export function groupsFromIdToken(idToken: string | undefined): string[] {
  if (!idToken) return [];
  const raw = decodeJwtPayload(idToken)["cognito:groups"];
  return Array.isArray(raw) ? raw.map(String) : [];
}

let tokenEndpoint: string | undefined;

async function refreshIdToken(token: JWT): Promise<JWT> {
  try {
    if (!tokenEndpoint) {
      const discovery = await fetch(`${config.cognito.issuer}/.well-known/openid-configuration`);
      tokenEndpoint = (await discovery.json()).token_endpoint as string;
    }
    const basic = Buffer.from(`${config.cognito.clientId}:${config.cognito.clientSecret}`).toString("base64");
    const res = await fetch(tokenEndpoint, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", authorization: `Basic ${basic}` },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: config.cognito.clientId,
        refresh_token: String(token.refreshToken),
      }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.error ?? "refresh failed");
    return {
      ...token,
      idToken: body.id_token,
      expiresAt: Math.floor(Date.now() / 1000) + Number(body.expires_in ?? 3600),
      groups: groupsFromIdToken(body.id_token),
      error: undefined,
    };
  } catch {
    return { ...token, error: "RefreshTokenError" };
  }
}

export const authOptions: NextAuthOptions = {
  providers:
    config.authMode === "cognito"
      ? [
          CognitoProvider({
            clientId: config.cognito.clientId,
            clientSecret: config.cognito.clientSecret,
            issuer: config.cognito.issuer,
          }),
        ]
      : [],
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  callbacks: {
    async jwt({ token, account }) {
      if (account) {
        return {
          ...token,
          idToken: account.id_token,
          refreshToken: account.refresh_token,
          expiresAt: account.expires_at,
          groups: groupsFromIdToken(account.id_token),
        };
      }
      if (typeof token.expiresAt === "number" && Date.now() / 1000 < token.expiresAt - 60) return token;
      return refreshIdToken(token);
    },
    // Tokens stay server-side: the client session only learns identity and roles.
    async session({ session, token }) {
      return {
        ...session,
        groups: (token.groups as string[] | undefined) ?? [],
        error: token.error as string | undefined,
      };
    },
  },
};
