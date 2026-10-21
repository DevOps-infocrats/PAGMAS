"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { createContext, Suspense, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ClientGate } from "./client-gate";

/**
 * Thin brand-gradient bar shown while navigating between routes. It reflects
 * navigation only (start → route committed); it never shows fake percentages.
 */
const Ctx = createContext<{ start: () => void }>({ start: () => {} });

export function useNavigationProgress() {
  return useContext(Ctx);
}

export function NavigationProgressProvider({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<"idle" | "running" | "finishing">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const start = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    setPhase("running");
    // Safety net: never leave the bar running if a navigation is cancelled.
    timer.current = setTimeout(() => setPhase("idle"), 8000);
  }, []);

  const finish = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    setPhase((p) => (p === "idle" ? p : "finishing"));
    timer.current = setTimeout(() => setPhase("idle"), 350);
  }, []);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as HTMLElement | null)?.closest("a");
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const url = new URL(a.href, location.href);
      if (url.origin !== location.origin) return;
      if (url.pathname + url.search === location.pathname + location.search) return;
      start();
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [start]);

  const value = useMemo(() => ({ start }), [start]);

  return (
    <Ctx.Provider value={value}>
      {phase !== "idle" && (
        <div
          className="route-progress"
          role="progressbar"
          aria-label="Loading page"
          style={{ width: phase === "running" ? "70%" : "100%", opacity: phase === "finishing" ? 0 : 1 }}
        />
      )}
      <ClientGate>
        <Suspense fallback={null}>
          <RouteWatcher onChange={finish} />
        </Suspense>
      </ClientGate>
      {children}
    </Ctx.Provider>
  );
}

function RouteWatcher({ onChange }: { onChange: () => void }) {
  const pathname = usePathname();
  const search = useSearchParams().toString();
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    onChange();
  }, [pathname, search, onChange]);
  return null;
}
