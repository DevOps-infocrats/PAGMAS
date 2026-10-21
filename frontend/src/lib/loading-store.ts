"use client";

import { useSyncExternalStore } from "react";

/**
 * Counts API requests that are in flight so the shell can show one global
 * loading bar. Every `track()` must be paired with the returned `done()`.
 */
let pending = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function track(): () => void {
  pending += 1;
  emit();
  let finished = false;
  return () => {
    if (finished) return;
    finished = true;
    pending = Math.max(0, pending - 1);
    emit();
  };
}

const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};

/** True while at least one tracked request is still loading. */
export function useIsLoadingData(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => pending > 0,
    () => false,
  );
}
