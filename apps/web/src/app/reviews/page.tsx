"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/Toast";
import { Card, ErrorNotice, PageHeader, Spinner, StatTile } from "@/components/ui";
import { fetcher, HttpError } from "@/lib/fetcher";
import type { ReviewStats } from "@/lib/types";
import { claimNext } from "./claim";

export default function ReviewsPage() {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const { data, error, isLoading } = useSWR<ReviewStats>("reviews/stats", fetcher, { refreshInterval: 3000 });

  async function claim() {
    setBusy(true);
    try {
      const task = await claimNext();
      if (task) router.push(`/reviews/${task.task_id}`);
      else toast("Queue empty — nothing to review right now", "info");
    } catch (e) {
      toast(e instanceof HttpError ? `${e.status}: ${e.message}` : String(e), "bad");
    } finally {
      setBusy(false);
    }
  }

  if (error instanceof HttpError && error.status === 403) {
    return (
      <>
        <PageHeader title="Review queue" />
        <ErrorNotice error="You need the reviewer role to work the review queue." />
      </>
    );
  }

  return (
    <>
      <PageHeader title="Review queue" subtitle="Low-confidence and audit-sampled extractions awaiting a human"
        actions={<button className="btn btn-primary" disabled={busy} onClick={claim}>{busy ? "Claiming…" : "Claim next task"}</button>} />
      <ErrorNotice error={error} />
      {isLoading && <Spinner />}
      {data && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatTile label="Ready" value={data.ready} tone={data.ready > 50 ? "warn" : "default"} />
          <StatTile label="Claimed" value={data.claimed} />
          <StatTile label="Done today" value={data.done_today} tone="ok" />
        </div>
      )}
      <Card title="How review works" className="mt-4">
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
          <li>Claiming takes a 5-minute lease; it renews automatically while the task is open.</li>
          <li>Correct the supplier, PO and line items, then submit (⌘/Ctrl + Enter). Stock updates immediately.</li>
          <li>Release (Esc) returns the task to the queue. Abandoned leases are re-queued by the reaper.</li>
          <li>Your corrections become ground truth for model and prompt evaluation.</li>
        </ul>
      </Card>
    </>
  );
}
