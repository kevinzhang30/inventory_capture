"use client";

import { useMemo, useState } from "react";
import {
  Bar, CartesianGrid, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import useSWR from "swr";
import { Badge, Card, EmptyState, ErrorNotice, PageHeader, Spinner, StatTile } from "@/components/ui";
import { pct } from "@/lib/confidence";
import { fetcher } from "@/lib/fetcher";
import type { EvalRun } from "@/lib/types";

const key = (r: Pick<EvalRun, "model_id" | "prompt_version">) => `${r.model_id}|${r.prompt_version}`;

export default function EvalPage() {
  const latest = useSWR<{ items: EvalRun[] }>("eval/latest", fetcher);
  const combos = useMemo(() => {
    const seen = new Map<string, EvalRun>();
    for (const r of latest.data?.items ?? []) if (!seen.has(key(r)) || r.kind === "nightly") seen.set(key(r), r);
    return [...seen.values()];
  }, [latest.data]);
  const [selected, setSelected] = useState<string | null>(null);
  const current = combos.find((c) => key(c) === selected) ?? combos[0];
  const [model, prompt] = current ? [current.model_id, current.prompt_version] : ["", ""];
  const runs = useSWR<{ items: EvalRun[] }>(
    current ? `eval/runs?model_id=${encodeURIComponent(model)}&prompt_version=${encodeURIComponent(prompt)}&limit=90` : null,
    fetcher,
  );

  const series = useMemo(() => (runs.data?.items ?? []).filter((r) => r.kind === "nightly").slice().reverse().map((r) => ({
    date: r.created_at.slice(0, 10),
    doc: r.metrics.document_exact_match,
    line: r.metrics.line_item_exact_match,
    f1: r.metrics.fields.sku.f1,
  })), [runs.data]);

  const latestRun = runs.data?.items[0] ?? current;
  const calibration = (latestRun?.metrics.calibration ?? []).map((b) => ({
    bin: `${b.bin_lo.toFixed(1)}–${b.bin_hi.toFixed(1)}`,
    accuracy: b.accuracy,
    ideal: (b.bin_lo + b.bin_hi) / 2,
    count: b.count,
  }));

  return (
    <>
      <PageHeader title="Extraction evaluation" subtitle="Field-level accuracy and confidence calibration from reviewer ground truth"
        actions={combos.length > 0 && (
          <select className="input w-auto" value={current ? key(current) : ""} onChange={(e) => setSelected(e.target.value)} aria-label="model and prompt version">
            {combos.map((c) => <option key={key(c)} value={key(c)}>{c.model_id} · {c.prompt_version}</option>)}
          </select>
        )} />
      <ErrorNotice error={latest.error ?? runs.error} />
      {latest.isLoading && <Spinner />}
      {latest.data && combos.length === 0 && (
        <EmptyState title="No evaluation runs yet">Runs appear after the nightly job or `make eval-run` with --save-db.</EmptyState>
      )}
      {latestRun && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            <StatTile label="Document exact" value={pct(latestRun.metrics.document_exact_match)} hint={`${latestRun.metrics.n_extractions} docs`} />
            <StatTile label="Line exact" value={pct(latestRun.metrics.line_item_exact_match)} hint={`${latestRun.metrics.n_line_items} lines`} />
            <StatTile label="SKU F1" value={pct(latestRun.metrics.fields.sku.f1)}
              hint={`P ${pct(latestRun.metrics.fields.sku.precision)} · R ${pct(latestRun.metrics.fields.sku.recall)}`} />
            <StatTile label="Qty / PO / supplier" value={<span className="text-base">{pct(latestRun.metrics.fields.qty.accuracy, 0)} / {pct(latestRun.metrics.fields.po_number.accuracy, 0)} / {pct(latestRun.metrics.fields.supplier.accuracy, 0)}</span>} />
            <StatTile label="Recommended threshold" value={latestRun.metrics.recommended_threshold ?? "—"}
              hint={`ECE ${latestRun.metrics.ece ?? "—"} · target precision ${pct(latestRun.metrics.target_precision, 0)}`} />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Accuracy over time (nightly)">
              {series.length === 0 ? <EmptyState title="No nightly runs for this combination" /> : (
                <div className="h-64">
                  <ResponsiveContainer>
                    <LineChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeOpacity={0.2} />
                      <XAxis dataKey="date" fontSize={11} />
                      <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} fontSize={11} />
                      <Tooltip formatter={(v: number) => pct(v)} />
                      <Legend />
                      <Line type="monotone" dataKey="doc" name="Document exact" stroke="rgb(var(--accent))" dot={false} />
                      <Line type="monotone" dataKey="line" name="Line exact" stroke="rgb(var(--ok))" dot={false} />
                      <Line type="monotone" dataKey="f1" name="SKU F1" stroke="rgb(var(--warn))" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </Card>
            <Card title="Calibration (reliability diagram)" actions={<Badge>{latestRun.kind}</Badge>}>
              <div className="h-64">
                <ResponsiveContainer>
                  <ComposedChart data={calibration} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeOpacity={0.2} />
                    <XAxis dataKey="bin" fontSize={10} />
                    <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} fontSize={11} />
                    <Tooltip formatter={(v: number, name: string) => (name === "Fields" ? v : pct(v))} />
                    <Legend />
                    <Bar dataKey="accuracy" name="Observed accuracy" fill="rgb(var(--accent))" />
                    <Line dataKey="ideal" name="Perfect calibration" stroke="rgb(var(--muted))" strokeDasharray="4 4" dot={false} />
                    {latestRun.metrics.recommended_threshold !== null && (
                      <ReferenceLine y={latestRun.metrics.target_precision} stroke="rgb(var(--ok))" strokeDasharray="2 2" />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-2 text-xs text-muted">Bars below the dashed line mean the model is over-confident in that bin. Field counts per bin: {calibration.map((c) => c.count).join(" · ")}</p>
            </Card>
          </div>

          <Card title="Model and prompt comparison (latest run each)">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr><th className="th">Model</th><th className="th">Prompt</th><th className="th">Kind</th><th className="th text-right">Docs</th><th className="th text-right">Doc exact</th><th className="th text-right">SKU F1</th><th className="th text-right">Qty</th><th className="th text-right">ECE</th><th className="th text-right">Threshold</th></tr></thead>
                <tbody>
                  {(latest.data?.items ?? []).map((r) => (
                    <tr key={r.run_id} className={current && key(r) === key(current) ? "bg-accent/5" : ""}>
                      <td className="td font-mono text-xs">{r.model_id}</td>
                      <td className="td">{r.prompt_version}</td>
                      <td className="td"><Badge>{r.kind}</Badge></td>
                      <td className="td text-right tabular-nums">{r.metrics.n_extractions}</td>
                      <td className="td text-right tabular-nums">{pct(r.metrics.document_exact_match)}</td>
                      <td className="td text-right tabular-nums">{pct(r.metrics.fields.sku.f1)}</td>
                      <td className="td text-right tabular-nums">{pct(r.metrics.fields.qty.accuracy)}</td>
                      <td className="td text-right tabular-nums">{r.metrics.ece ?? "—"}</td>
                      <td className="td text-right tabular-nums">{r.metrics.recommended_threshold ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </>
  );
}
