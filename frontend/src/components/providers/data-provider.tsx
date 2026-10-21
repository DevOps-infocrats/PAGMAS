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

export function DataProvider({ children }: { children: React.ReactNode }) {
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [metaError, setMetaError] = useState<Error | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [lastRefreshed, setLastRefreshed] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const done = track();
    api
      .getMeta()
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
