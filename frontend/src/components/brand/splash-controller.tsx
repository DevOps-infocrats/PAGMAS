"use client";

import { useEffect } from "react";

const MIN_VISIBLE_MS = 1100;

/** Hides the splash once the app has hydrated and the minimum display time has passed. */
export function SplashController({ storageKey }: { storageKey: string }) {
  useEffect(() => {
    const root = document.documentElement;
    if (root.dataset.splash === "done") return;
    const elapsed = performance.now();
    const wait = Math.max(0, MIN_VISIBLE_MS - elapsed);
    const t = setTimeout(() => {
      root.dataset.splash = "done";
      try {
        sessionStorage.setItem(storageKey, "1");
      } catch {
        /* ignore – splash will simply show again next load */
      }
    }, wait);
    return () => clearTimeout(t);
  }, [storageKey]);
  return null;
}
