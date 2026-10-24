"use client";

import Link from "next/link";
import useSWR from "swr";
import { Badge, Card, EmptyState, ErrorNotice, PageHeader, Spinner, StatTile } from "@/components/ui";
import { fetcher } from "@/lib/fetcher";
import { fmtAgo, fmtNum } from "@/lib/format";
import type { DashboardSummary } from "@/lib/types";

export default function DashboardPage() {
  // Design §6.5: SWR polling first; push is a later option.
  const { data, error, isLoading } = useSWR<DashboardSummary>("dashboard/summary", fetcher, { refreshInterval: 2000 });

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Live view of receiving activity · refreshes every 2 s" />
      <ErrorNotice error={error} />
      {isLoading && <Spinner />}
      {data && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatTile label="Captures, last hour" value={fmtNum(data.captures_last_hour)} />
            <StatTile label="Pending reviews" value={fmtNum(data.pending_reviews)} tone={data.pending_reviews > 50 ? "warn" : "default"}
              hint={<Link className="text-accent hover:underline" href="/reviews">Open queue →</Link>} />
            <StatTile label="Reviews in progress" value={fmtNum(data.claimed_reviews)} />
          </div>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Low stock" actions={<Badge tone={data.low_stock.length ? "warn" : "ok"}>{data.low_stock.length}</Badge>}>
              {data.low_stock.length === 0 ? (
                <EmptyState title="Nothing below its reorder point" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr><th className="th">SKU</th><th className="th">Part</th><th className="th text-right">On hand</th><th className="th text-right">Reorder at</th></tr></thead>
                    <tbody>
                      {data.low_stock.map((p) => (
                        <tr key={p.sku}>
                          <td className="td font-mono"><Link className="text-accent hover:underline" href={`/parts/${p.sku}`}>{p.sku}</Link></td>
                          <td className="td">{p.name}</td>
                          <td className={`td text-right tabular-nums ${p.on_hand_total <= 0 ? "text-bad" : "text-warn"}`}>{p.on_hand_total}</td>
                          <td className="td text-right tabular-nums text-muted">{p.reorder_point}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
            <Card title="Recent stock movements">
              {data.recent_movements.length === 0 ? (
                <EmptyState title="No movements yet">Scan something on a capture station.</EmptyState>
              ) : (
                <ul className="divide-y divide-line">
                  {data.recent_movements.map((m) => (
                    <li key={m.movement_id} className="flex items-center justify-between gap-3 py-1.5 text-sm">
                      <span className="min-w-0 truncate">
                        <Link className="font-mono text-accent hover:underline" href={`/parts/${m.sku}`}>{m.sku}</Link>
                        <span className="text-muted"> @ {m.location_id}</span>
                      </span>
                      <span className="flex shrink-0 items-center gap-3">
                        <Badge tone={m.qty_delta >= 0 ? "ok" : "bad"}>{m.qty_delta > 0 ? `+${m.qty_delta}` : m.qty_delta}</Badge>
                        <span className="w-16 text-right text-xs text-muted">{fmtAgo(m.created_at)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
