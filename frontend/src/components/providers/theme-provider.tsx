"use client";

import { createContext, useCallback, useContext, useEffect, useState, useSyncExternalStore } from "react";

import { THEME_STORAGE_KEY as STORAGE_KEY, type ThemePreference } from "@/lib/theme";

export type { ThemePreference };

interface ThemeContextValue {
  preference: ThemePreference;
  resolved: "light" | "dark";
  setPreference: (t: ThemePreference) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readPreference(): ThemePreference {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "dark" || v === "system" ? v : "light";
  } catch {
    return "light";
  }
}

const subscribeDark = (cb: () => void) => {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => obs.disconnect();
};

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [stored, setPref] = useState<ThemePreference | null>(null);
  const preference = stored ?? "light";
  const resolved = useSyncExternalStore(
    subscribeDark,
    () => (document.documentElement.classList.contains("dark") ? "dark" : "light"),
    () => "light" as const,
  );

  useEffect(() => {
    // Sync the stored preference after hydration (server always renders "light").
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPref(readPreference());
  }, []);

  useEffect(() => {
    if (stored == null) return; // wait until the stored preference is known
    const apply = () => {
      const dark = preference === "dark" || (preference === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
      document.documentElement.classList.toggle("dark", dark);
    };
    apply();
    if (preference !== "system") return;
    const mq = matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [stored, preference]);

  const setPreference = useCallback((t: ThemePreference) => {
    try {
      localStorage.setItem(STORAGE_KEY, t);
    } catch {
      /* storage unavailable – preference lasts for this page view only */
    }
    setPref(t);
  }, []);

  return <ThemeContext.Provider value={{ preference, resolved, setPreference }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("ThemeProvider missing");
  return ctx;
}
