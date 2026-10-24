"use client";

import useSWR from "swr";
import { Badge, Card, EmptyState, ErrorNotice, PageHeader, Spinner, StatTile } from "@/components/ui";
import { fetcher } from "@/lib/fetcher";
import type { PartDetail } from "@/lib/types";

export default function PartPage({ params }: { params: { sku: string } }) {
  const sku = decodeURIComponent(params.sku);
  const { data, error, isLoading } = useSWR<PartDetail>(`parts/${encodeURIComponent(sku)}`, fetcher, { refreshInterval: 2000 });

  return (
    <>
      <PageHeader title={sku} subtitle={data ? `${data.name} · ${data.part_number}` : undefined}
        actions={data && <Badge tone={data.stock.source === "cache" ? "ok" : "default"}>served from {data.stock.source}</Badge>} />
      <ErrorNotice error={error} />
      {isLoading && <Spinner />}
      {data && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="On hand" value={data.stock.on_hand_total}
              tone={data.reorder_point > 0 && data.stock.on_hand_total <= data.reorder_point ? "warn" : "default"} />
            <StatTile label="Reorder point" value={data.reorder_point} />
            <StatTile label="Category" value={<span className="text-base">{data.category}</span>} />
            <StatTile label="Supplier" value={<span className="text-base">{data.supplier_name ?? data.supplier_id ?? "—"}</span>} />
          </div>
          <Card title="Stock by location">
            {data.stock.locations.length === 0 ? (
              <EmptyState title="No stock recorded" />
            ) : (
              <table className="w-full text-sm">
                <thead><tr><th className="th">Location</th><th className="th text-right">On hand</th><th className="th text-right">Version</th></tr></thead>
                <tbody>
                  {data.stock.locations.map((l) => (
                    <tr key={l.location_id}>
                      <td className="td font-mono">{l.location_id}</td>
                      <td className="td text-right tabular-nums">{l.on_hand}</td>
                      <td className="td text-right tabular-nums text-muted">{l.version}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      )}
    </>
  );
}
