import type { NextFetchEvent, NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { withAuth, type NextRequestWithAuth } from "next-auth/middleware";

const requireLogin = withAuth({ pages: { signIn: "/login" } });

export default function middleware(req: NextRequest, event: NextFetchEvent) {
  if (process.env.AUTH_MODE !== "cognito") return NextResponse.next();
  return requireLogin(req as NextRequestWithAuth, event);
}

export const config = {
  matcher: ["/((?!api/auth|login|_next/static|_next/image|favicon.ico).*)"],
};
