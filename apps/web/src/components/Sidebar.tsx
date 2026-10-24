"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { signOut } from "next-auth/react";
import { DevIdentity } from "./DevIdentity";

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/search", label: "Search" },
  { href: "/reviews", label: "Review queue", roles: ["reviewer", "admin"] },
  { href: "/eval", label: "Extraction eval" },
];

export function Sidebar({ user, groups, authMode }: { user: string; groups: string[]; authMode: "dev" | "cognito" }) {
  const path = usePathname();
  const visible = NAV.filter((n) => !n.roles || n.roles.some((r) => groups.includes(r)));
  return (
    <aside className="flex w-full shrink-0 flex-col border-b border-line bg-panel md:min-h-screen md:w-56 md:border-b-0 md:border-r">
      <div className="px-4 py-4">
        <div className="text-sm font-semibold">Inventory Capture</div>
        <div className="text-xs text-muted">Receiving operations</div>
      </div>
      <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-0">
        {visible.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <Link key={n.href} href={n.href}
              className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm ${active ? "bg-accent/10 font-medium text-accent" : "text-muted hover:bg-bg hover:text-ink"}`}>
              {n.label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto hidden border-t border-line p-3 text-xs md:block">
        {authMode === "dev" ? (
          <DevIdentity user={user} groups={groups} />
        ) : (
          <div className="space-y-1">
            <div className="truncate font-medium">{user}</div>
            <div className="text-muted">{groups.join(", ") || "no roles"}</div>
            <button className="btn mt-1 w-full justify-center" onClick={() => signOut({ callbackUrl: "/login" })}>Sign out</button>
          </div>
        )}
      </div>
    </aside>
  );
}
