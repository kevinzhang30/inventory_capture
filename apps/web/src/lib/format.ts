export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "medium" });
}

export function fmtAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const s = Math.round((now - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const fmtNum = (n: number | null | undefined) => (n === null || n === undefined ? "—" : n.toLocaleString());
