"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Pager } from "@/components/Pager";
import { Tabs } from "@/components/Tabs";
import { Badge, EmptyState, ErrorNotice, PageHeader, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/fetcher";
import { fmtTime } from "@/lib/format";
import { parseDocumentsQuery, parsePartsQuery, toSearchParams, toggle } from "@/lib/query";
import type { DocumentDoc, Facet, PartDoc, SearchResult } from "@/lib/types";

const SIZE = 20;
type Tab = "parts" | "documents";

function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function FacetGroup({ title, facets, selected, onToggle }: {
  title: string; facets: Facet[] | undefined; selected: string[]; onToggle: (v: string) => void;
}) {
  if (!facets?.length && !selected.length) return null;
  return (
    <fieldset className="mb-4">
      <legend className="label">{title}</legend>
      {(facets ?? []).map((f) => (
        <label key={f.key} className="flex items-center justify-between gap-2 py-0.5 text-sm">
          <span className="flex items-center gap-2">
            <input type="checkbox" checked={selected.includes(f.key)} onChange={() => onToggle(f.key)} />
            {f.key}
          </span>
          <span className="tabular-nums text-xs text-muted">{f.count}</span>
        </label>
      ))}
    </fieldset>
  );
}

function SearchInner() {
  const router = useRouter();
  const params = useSearchParams();
  const tab: Tab = params.get("tab") === "documents" ? "documents" : "parts";
  const parts = parsePartsQuery(params);
  const docs = parseDocumentsQuery(params);
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q);

  const push = (state: Record<string, string | string[] | number | undefined>) =>
    router.replace(`/search?${toSearchParams({ tab: tab === "parts" ? undefined : tab, ...state })}`);

  useEffect(() => {
    if (dq !== (params.get("q") ?? "")) {
      push(tab === "parts" ? { ...parts, q: dq, page: 1 } : { ...docs, q: dq, page: 1 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dq]);

  const apiPath = useMemo(() => {
    const p = tab === "parts"
      ? toSearchParams({ q: parts.q, category: parts.category, supplier: parts.supplier, site: parts.site, page: parts.page, size: SIZE })
      : toSearchParams({ q: docs.q, supplier: docs.supplier, from: docs.from, to: docs.to, page: docs.page, size: SIZE });
    return `search/${tab}?${p}`;
  }, [tab, parts, docs]);

  const { data, error, isLoading } = useSWR<SearchResult<PartDoc | DocumentDoc>>(apiPath, fetcher, { keepPreviousData: true });

  return (
    <>
      <PageHeader title="Search" subtitle="Fuzzy part numbers, names and packing-slip text" />
      <Tabs<Tab> tabs={[{ id: "parts", label: "Parts" }, { id: "documents", label: "Documents" }]} value={tab}
        onChange={(t) => router.replace(`/search?${toSearchParams({ tab: t === "parts" ? undefined : t, q })}`)} />
      <input className="input mb-4 max-w-xl" placeholder={tab === "parts" ? "Part number, SKU or name…" : "PO number, supplier or slip text…"}
        value={q} onChange={(e) => setQ(e.target.value)} autoFocus aria-label="search query" />
      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className="lg:w-56 lg:shrink-0">
          {tab === "parts" ? (
            <>
              <FacetGroup title="Category" facets={data?.facets.category} selected={parts.category}
                onToggle={(v) => push({ ...parts, category: toggle(parts.category, v), page: 1 })} />
              <FacetGroup title="Supplier" facets={data?.facets.supplier} selected={parts.supplier}
                onToggle={(v) => push({ ...parts, supplier: toggle(parts.supplier, v), page: 1 })} />
              <FacetGroup title="Site (in stock)" facets={data?.facets.site} selected={parts.site}
                onToggle={(v) => push({ ...parts, site: toggle(parts.site, v), page: 1 })} />
            </>
          ) : (
            <>
              <FacetGroup title="Supplier" facets={data?.facets.supplier} selected={docs.supplier}
                onToggle={(v) => push({ ...docs, supplier: toggle(docs.supplier, v), page: 1 })} />
              <label className="label" htmlFor="from">Captured from</label>
              <input id="from" type="date" className="input mb-2" value={docs.from} onChange={(e) => push({ ...docs, from: e.target.value, page: 1 })} />
              <label className="label" htmlFor="to">Captured to</label>
              <input id="to" type="date" className="input" value={docs.to} onChange={(e) => push({ ...docs, to: e.target.value, page: 1 })} />
            </>
          )}
        </aside>
        <div className="min-w-0 flex-1">
          <ErrorNotice error={error} />
          {isLoading && !data && <Spinner />}
          {data && data.items.length === 0 && <EmptyState title="No matches">Try fewer filters or a shorter query.</EmptyState>}
          {data && data.items.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-line bg-panel">
              {tab === "parts" ? <PartsTable items={data.items as PartDoc[]} /> : <DocsTable items={data.items as DocumentDoc[]} />}
            </div>
          )}
          {data && data.total > 0 && (
            <Pager page={tab === "parts" ? parts.page : docs.page} size={SIZE} total={data.total}
              onPage={(page) => push(tab === "parts" ? { ...parts, page } : { ...docs, page })} />
          )}
        </div>
      </div>
    </>
  );
}

function PartsTable({ items }: { items: PartDoc[] }) {
  return (
    <table className="w-full text-sm">
      <thead><tr><th className="th">SKU</th><th className="th">Part number</th><th className="th">Name</th><th className="th">Category</th><th className="th">Supplier</th><th className="th text-right">On hand</th></tr></thead>
      <tbody>
        {items.map((p) => (
          <tr key={p.sku} className="hover:bg-bg">
            <td className="td font-mono"><Link className="text-accent hover:underline" href={`/parts/${p.sku}`}>{p.sku}</Link></td>
            <td className="td font-mono">{p.part_number}</td>
            <td className="td">{p.name}</td>
            <td className="td"><Badge>{p.category}</Badge></td>
            <td className="td">{p.supplier_name ?? p.supplier_id}</td>
            <td className={`td text-right tabular-nums ${(p.on_hand_total ?? 0) <= p.reorder_point && p.reorder_point > 0 ? "text-warn" : ""}`}>{p.on_hand_total ?? 0}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DocsTable({ items }: { items: DocumentDoc[] }) {
  const tone = { auto_applied: "ok", pending_review: "warn", reviewed: "accent" } as const;
  return (
    <table className="w-full text-sm">
      <thead><tr><th className="th">Captured</th><th className="th">PO</th><th className="th">Supplier</th><th className="th">Lines</th><th className="th">Status</th></tr></thead>
      <tbody>
        {items.map((d) => (
          <tr key={d.capture_id} className="hover:bg-bg">
            <td className="td"><Link className="text-accent hover:underline" href={`/captures/${d.capture_id}`}>{fmtTime(d.captured_at)}</Link></td>
            <td className="td font-mono">{d.po_number ?? "—"}</td>
            <td className="td">{d.supplier ?? "—"}</td>
            <td className="td text-muted">{d.line_items.map((l) => l.sku).filter(Boolean).slice(0, 3).join(", ")}{d.line_items.length > 3 ? "…" : ""}</td>
            <td className="td"><Badge tone={tone[d.status]}>{d.status.replace("_", " ")}</Badge></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <SearchInner />
    </Suspense>
  );
}
