"use client";

import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

function LoginInner() {
  const params = useSearchParams();
  const callbackUrl = params.get("callbackUrl") ?? "/";
  return (
    <div className="mx-auto mt-24 max-w-sm rounded-lg border border-line bg-panel p-6 text-center">
      <h1 className="text-lg font-semibold">Inventory Capture</h1>
      <p className="mt-1 text-sm text-muted">Sign in with your company account.</p>
      {params.get("error") && <p className="mt-3 text-sm text-bad">Sign-in failed. Try again.</p>}
      <button className="btn btn-primary mt-5 w-full justify-center" onClick={() => signIn("cognito", { callbackUrl })}>
        Sign in
      </button>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}
