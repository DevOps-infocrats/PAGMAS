"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, type MetaResponse } from "@/lib/api";
import { track } from "@/lib/loading-store";

interface DataContextValue {
  meta: MetaResponse | null;
  metaError: Error | null;
  refreshKey: number;
  /** Re-requests every query on the page. Mock mode: re-reads the same demo data. */
  refresh: () => void;
  lastRefreshed: number | null;
}

const DataContext = createContext<DataContextValue | null>(null);

/** One /meta request at a time: React's dev-mode double effect (and remounts) share it instead of asking twice. */
let metaInFlight: Promise<MetaResponse> | null = null;
function loadMeta(): Promise<MetaResponse> {
  if (!metaInFlight) {
    const p = api.getMeta();
    metaInFlight = p;
    const clear = () => {
      if (metaInFlight === p) metaInFlight = null;
    };
    p.then(clear, clear);
  }
  return metaInFlight;
}

export function DataProvider({ children }: { children: React.ReactNode }) {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [metaError, setMetaError] = useState<Error | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [lastRefreshed, setLastRefreshed] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const done = track();
    loadMeta()
      .then(
        (m) => !cancelled && setMeta(m),
        (e: unknown) => !cancelled && setMetaError(e instanceof Error ? e : new Error(String(e))),
      )
      .finally(done);
    return () => {
      cancelled = true;
      done();
    };
  }, []);

  const refresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
    setLastRefreshed(Date.now());
  }, []);

  const value = useMemo(
    () => ({ meta, metaError, refreshKey, refresh, lastRefreshed }),
    [meta, metaError, refreshKey, refresh, lastRefreshed],
  );
  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

function useDataContext() {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("DataProvider missing");
  return ctx;
}

export const useMeta = () => useDataContext().meta;
export const useMetaError = () => useDataContext().metaError;
export const useRefreshKey = () => useDataContext().refreshKey;
export const useRefresh = () => {
  const { refresh, lastRefreshed } = useDataContext();
  return { refresh, lastRefreshed };
};
