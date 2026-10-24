"use client";

import Link from "next/link";
import useSWR from "swr";
import { ImageViewer } from "@/components/ImageViewer";
import { Badge, Card, ConfidenceBadge, EmptyState, ErrorNotice, PageHeader, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/fetcher";
import { fmtTime } from "@/lib/format";
import type { CaptureDetail } from "@/lib/types";

export default function CapturePage({ params }: { params: { id: string } }) {
  const { data, error, isLoading } = useSWR<CaptureDetail>(`captures/${params.id}`, fetcher);
  const c = data?.capture;

  return (
    <>
      <PageHeader title="Capture" subtitle={<span className="font-mono">{params.id}</span>}
        actions={c && <Badge tone={c.status === "rejected" || c.status === "failed" ? "bad" : c.status === "pending_review" ? "warn" : "ok"}>{c.status}</Badge>} />
      <ErrorNotice error={error} />
      {isLoading && <Spinner />}
      {data && c && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <div className="space-y-4">
            <Card title="Details">
              <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-muted">Kind</dt><dd>{c.kind}</dd>
                <dt className="text-muted">Site / station</dt><dd>{c.site_id} / {c.station_id}</dd>
                <dt className="text-muted">Operator</dt><dd>{c.operator_id ?? "—"}</dd>
                <dt className="text-muted">Captured</dt><dd>{fmtTime(c.captured_at)}</dd>
                <dt className="text-muted">Received</dt><dd>{fmtTime(c.received_at)}</dd>
                {c.error && (<><dt className="text-muted">Error</dt><dd className="text-bad">{c.error}</dd></>)}
              </dl>
            </Card>
            <Card title="Extractions">
              {data.extractions.length === 0 ? <EmptyState title="No extractions" /> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr><th className="th">Model</th><th className="th">Prompt</th><th className="th">Min conf.</th><th className="th text-right">Tokens</th><th className="th text-right">Latency</th><th className="th">Review</th></tr></thead>
                    <tbody>
                      {data.extractions.map((e) => (
                        <tr key={e.extraction_id}>
                          <td className="td font-mono text-xs">{e.model_id}</td>
                          <td className="td">{e.prompt_version}</td>
                          <td className="td">{e.error ? <Badge tone="bad">error</Badge> : <ConfidenceBadge value={e.min_confidence} />}</td>
                          <td className="td text-right tabular-nums">{(e.input_tokens ?? 0) + (e.output_tokens ?? 0)}</td>
                          <td className="td text-right tabular-nums">{e.latency_ms ?? "—"} ms</td>
                          <td className="td">{e.task_id ? <Badge tone={e.review_status === "done" ? "ok" : "warn"}>{e.reason} · {e.review_status}</Badge> : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data.extractions.some((e) => e.ground_truth) && (
                <details className="mt-3 text-sm">
                  <summary className="cursor-pointer text-muted">Ground truth</summary>
                  <pre className="mt-2 overflow-x-auto rounded bg-bg p-2 text-xs">{JSON.stringify(data.extractions.find((e) => e.ground_truth)?.ground_truth, null, 2)}</pre>
                </details>
              )}
            </Card>
            <Card title="Stock movements">
              {data.movements.length === 0 ? <EmptyState title="No stock effect yet" /> : (
                <ul className="space-y-1 text-sm">
                  {data.movements.map((m) => (
                    <li key={m.movement_id}>
                      <Link className="font-mono text-accent hover:underline" href={`/parts/${m.sku}`}>{m.sku}</Link>{" "}
                      <Badge tone={m.qty_delta >= 0 ? "ok" : "bad"}>{m.qty_delta > 0 ? "+" : ""}{m.qty_delta}</Badge>{" "}
                      <span className="text-muted">@ {m.location_id} · {m.type}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
          {c.kind === "document" && (
            <Card title="Packing slip"><ImageViewer src={data.image_url} alt="packing slip" /></Card>
          )}
        </div>
      )}
    </>
  );
}
