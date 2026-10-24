"use client";

import { useRef, useState, type PointerEvent, type WheelEvent } from "react";

/** Zoom (wheel / buttons) and pan (drag) for packing-slip images. */
export function ImageViewer({ src, alt }: { src: string | null; alt: string }) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number } | null>(null);

  if (!src) return <div className="flex h-full items-center justify-center text-sm text-muted">No image</div>;
  if (src.includes(".pdf")) {
    return <iframe title={alt} src={src} className="h-full min-h-[480px] w-full rounded-md border border-line" />;
  }

  const zoom = (factor: number) => setScale((s) => Math.min(6, Math.max(0.5, s * factor)));
  const onWheel = (e: WheelEvent) => { e.preventDefault(); zoom(e.deltaY < 0 ? 1.1 : 0.9); };
  const onDown = (e: PointerEvent) => {
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX - offset.x, y: e.clientY - offset.y };
  };
  const onMove = (e: PointerEvent) => {
    if (drag.current) setOffset({ x: e.clientX - drag.current.x, y: e.clientY - drag.current.y });
  };

  return (
    <div className="relative h-full min-h-[480px] overflow-hidden rounded-md border border-line bg-bg">
      <div className="absolute right-2 top-2 z-10 flex gap-1">
        <button className="btn px-2" onClick={() => zoom(1.25)} aria-label="zoom in">+</button>
        <button className="btn px-2" onClick={() => zoom(0.8)} aria-label="zoom out">−</button>
        <button className="btn px-2" onClick={() => { setScale(1); setOffset({ x: 0, y: 0 }); }}>Reset</button>
      </div>
      <div className="h-full w-full cursor-grab touch-none active:cursor-grabbing" onWheel={onWheel}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => { drag.current = null; }}>
        <img src={src} alt={alt} draggable={false} className="max-w-none select-none"
          style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`, transformOrigin: "0 0", width: "100%" }} />
      </div>
    </div>
  );
}
