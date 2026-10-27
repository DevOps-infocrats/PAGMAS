"use client";

import { useEffect } from "react";

const MIN_VISIBLE_MS = 1700;
/** Lets the logo reveal finish even when the page itself loaded slowly. */
const MIN_AFTER_READY_MS = 600;

/** Hides the splash once the app has hydrated and the minimum display time has passed. */
export function SplashController() {
  useEffect(() => {
    const root = document.documentElement;
    if (root.dataset.splash === "done") return;
    const wait = Math.max(MIN_AFTER_READY_MS, MIN_VISIBLE_MS - performance.now());
    const t = setTimeout(() => {
      root.dataset.splash = "done";
    }, wait);
    return () => clearTimeout(t);
  }, []);
  return null;
}
