"use client";

/* Drag and drop with pointer events — mouse, pen and finger alike.
 *
 * Why not the browser's own HTML5 drag-and-drop: it does not work on phones at all, and in
 * Chrome it stopped starting after the first drag on the campaign page (measured 2026-10-05:
 * mousedown/mouseup arrived, dragstart never did). Pointer events have neither problem.
 *
 * Use: give each drop target `data-drop="<kind>"` (and `data-index` where it matters), call
 * `start(e, payload, label)` from onPointerDown, and handle the drop in `onDrop`. A press that
 * moves less than 6px is a click, so the same element can be clicked or dragged; `wasDrag()`
 * tells a click handler to ignore the click that ends a drag. */

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

export type DropTarget = { kind: string; index: number; el: HTMLElement };

function targetAt(x: number, y: number): DropTarget | null {
  const el = (document.elementFromPoint(x, y) as HTMLElement | null)?.closest<HTMLElement>("[data-drop]");
  if (!el) return null;
  return { kind: el.dataset.drop ?? "", index: Number(el.dataset.index ?? -1), el };
}

export function usePointerDrag<T>(onDrop: (payload: T, target: DropTarget) => void) {
  const live = useRef<{ payload: T; x: number; y: number; moved: boolean; label: string; ghost?: HTMLElement; over?: HTMLElement } | null>(null);
  const dropRef = useRef(onDrop);
  const lastDragEnd = useRef(0);
  const [dragging, setDragging] = useState<T | null>(null);
  dropRef.current = onDrop;

  const clear = () => {
    const s = live.current;
    s?.ghost?.remove();
    s?.over?.removeAttribute("data-over");
    document.body.classList.remove("u-dragging");
  };
  useEffect(() => () => clear(), []);

  const start = useCallback((e: ReactPointerEvent, payload: T, label: string) => {
    if (e.button !== 0) return;
    live.current = { payload, x: e.clientX, y: e.clientY, moved: false, label };

    // near the top or bottom edge the page scrolls by itself, so a far target can be reached
    let edge = 0;
    const tick = () => {
      if (!live.current) return;
      if (edge && live.current.moved) window.scrollBy(0, edge);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);

    const move = (ev: PointerEvent) => {
      const s = live.current;
      if (!s) return;
      edge = ev.clientY < 70 ? -14 : ev.clientY > window.innerHeight - 70 ? 14 : 0;
      if (!s.moved) {
        if (Math.hypot(ev.clientX - s.x, ev.clientY - s.y) < 6) return;
        s.moved = true;
        const g = document.createElement("div");
        g.className = "u-ghost";
        g.textContent = s.label;
        document.body.appendChild(g);
        s.ghost = g;
        document.body.classList.add("u-dragging");
        setDragging(s.payload);
      }
      ev.preventDefault();
      if (s.ghost) s.ghost.style.transform = `translate(${ev.clientX + 12}px, ${ev.clientY + 8}px)`;
      const t = targetAt(ev.clientX, ev.clientY);
      if (s.over !== t?.el) {
        s.over?.removeAttribute("data-over");
        t?.el.setAttribute("data-over", "");
        s.over = t?.el;
      }
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      const s = live.current;
      clear();
      live.current = null;
      setDragging(null);
      if (!s?.moved) return;
      lastDragEnd.current = Date.now();
      const t = ev.type === "pointerup" ? targetAt(ev.clientX, ev.clientY) : null;
      if (t) dropRef.current(s.payload, t);
    };
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  }, []);

  /** True right after a drag ended — the click that follows it is not a real click. */
  const wasDrag = useCallback(() => Date.now() - lastDragEnd.current < 250, []);

  return { start, dragging, wasDrag };
}
