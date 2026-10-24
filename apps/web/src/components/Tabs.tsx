"use client";

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: string }[]; value: T; onChange: (id: T) => void;
}) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
            value === t.id ? "border-accent text-accent" : "border-transparent text-muted hover:text-ink"}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
