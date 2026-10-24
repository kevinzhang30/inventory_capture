import type { ReactNode } from "react";
import { confidenceLevel, pct } from "@/lib/confidence";

export function Card({ title, actions, children, className = "" }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-lg border border-line bg-panel ${className}`}>
      {(title || actions) && (
        <header className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function StatTile({ label, value, hint, tone = "default" }: {
  label: string; value: ReactNode; hint?: ReactNode; tone?: "default" | "warn" | "bad" | "ok";
}) {
  const color = { default: "text-ink", warn: "text-warn", bad: "text-bad", ok: "text-ok" }[tone];
  return (
    <div className="rounded-lg border border-line bg-panel px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function Badge({ children, tone = "default" }: {
  children: ReactNode; tone?: "default" | "ok" | "warn" | "bad" | "accent";
}) {
  const cls = {
    default: "bg-line/60 text-ink",
    ok: "bg-ok/15 text-ok",
    warn: "bg-warn/15 text-warn",
    bad: "bg-bad/15 text-bad",
    accent: "bg-accent/15 text-accent",
  }[tone];
  return <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${cls}`}>{children}</span>;
}

export function ConfidenceBadge({ value }: { value: number | null | undefined }) {
  const level = confidenceLevel(value);
  const tone = ({ low: "bad", medium: "warn", high: "ok", unknown: "default" } as const)[level];
  return (
    <span title={`model confidence (${level})`}>
      <Badge tone={tone}>{pct(value, 0)}</Badge>
    </span>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-4 text-sm text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-accent" />
      {label}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line p-8 text-center">
      <div className="font-medium">{title}</div>
      {children && <div className="mt-1 text-sm text-muted">{children}</div>}
    </div>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div role="alert" className="rounded-md border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">{msg}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
