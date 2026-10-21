"use client";

import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * Renders `fallback` on the server and during hydration, then `children` on
 * the client. Used around URL-driven UI (useSearchParams) so the server never
 * bails out mid-render and leaves orphaned, hidden markup behind.
 */
export function ClientGate({ children, fallback = null }: { children: React.ReactNode; fallback?: React.ReactNode }) {
  const mounted = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  return <>{mounted ? children : fallback}</>;
}
