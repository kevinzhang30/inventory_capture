"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Tone = "info" | "ok" | "bad";
interface ToastItem { id: number; text: string; tone: Tone }

const ToastContext = createContext<(text: string, tone?: Tone) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, tone: Tone = "info") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs, { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className={`rounded-md px-3 py-2 text-sm text-white shadow-lg ${
            t.tone === "ok" ? "bg-ok" : t.tone === "bad" ? "bg-bad" : "bg-ink/90"}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
