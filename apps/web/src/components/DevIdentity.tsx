"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const ROLES = ["operator", "reviewer", "admin"];

export function DevIdentity({ user, groups }: { user: string; groups: string[] }) {
  const router = useRouter();
  const [name, setName] = useState(user);
  const [roles, setRoles] = useState(groups);

  async function save(nextRoles = roles) {
    await fetch("/api/dev-identity", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ user: name, groups: nextRoles }),
    });
    router.refresh();
  }

  return (
    <div className="space-y-2">
      <div className="font-semibold text-muted">Dev identity</div>
      <input className="input" value={name} onChange={(e) => setName(e.target.value)} onBlur={() => save()} aria-label="dev user" />
      <div className="flex flex-wrap gap-2">
        {ROLES.map((r) => (
          <label key={r} className="flex items-center gap-1">
            <input type="checkbox" checked={roles.includes(r)} onChange={() => {
              const next = roles.includes(r) ? roles.filter((x) => x !== r) : [...roles, r];
              setRoles(next);
              void save(next);
            }} />
            {r}
          </label>
        ))}
      </div>
    </div>
  );
}
