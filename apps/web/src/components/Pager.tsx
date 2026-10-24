"use client";

export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="mt-3 flex items-center justify-between text-sm text-muted">
      <span>{total.toLocaleString()} results · page {page} of {pages}</span>
      <div className="flex gap-2">
        <button className="btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
        <button className="btn" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}
