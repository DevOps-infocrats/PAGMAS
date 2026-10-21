"use client";

import { useCallback, useEffect, useState } from "react";
import { useRefreshKey } from "@/components/providers/data-provider";
import { track } from "@/lib/loading-store";

interface QueryState<T> {
  key: string;
  data?: T;
  error?: Error;
}

/**
 * Requests in flight, by full key. Components that ask for the same data at the same time (and React's
 * dev-mode double effect) share one request instead of making the server compute it several times.
 * Entries are removed when the request settles, so nothing stale is ever served from here.
 */
const inFlight = new Map<string, Promise<unknown>>();

function shared<T>(key: string, fetcher: () => Promise<T>): Promise<T> {
  let p = inFlight.get(key) as Promise<T> | undefined;
  if (!p) {
    p = fetcher();
    inFlight.set(key, p);
    const clear = () => {
      if (inFlight.get(key) === p) inFlight.delete(key);
    };
    p.then(clear, clear);
  }
  return p;
}

/**
 * Minimal data hook around the API layer. `key` must uniquely describe the
 * request (it changes → refetch). Results are discarded if a newer request
 * started meanwhile. The global Refresh control bumps `refreshKey`. Identical concurrent
 * requests are shared (see `inFlight`).
 */
export function useApiQuery<T>(key: string | null, fetcher: () => Promise<T>) {
  const refreshKey = useRefreshKey();
  const [local, setLocal] = useState(0);
  const fullKey = key == null ? null : `${key}#${refreshKey}.${local}`;
  const [state, setState] = useState<QueryState<T>>({ key: "" });

  useEffect(() => {
    if (fullKey == null) return;
    let cancelled = false;
    const done = track(); // global loading bar
    shared(fullKey, fetcher)
      .then(
        (data) => !cancelled && setState({ key: fullKey, data }),
        (error: unknown) =>
          !cancelled && setState({ key: fullKey, error: error instanceof Error ? error : new Error(String(error)) }),
      )
      .finally(done);
    return () => {
      cancelled = true;
      done();
    };
    // `fetcher` is intentionally excluded: the key fully describes the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullKey]);

  const settled = state.key === fullKey;
  const reload = useCallback(() => setLocal((n) => n + 1), []);

  return {
    data: settled ? state.data : undefined,
    /** Previous data while a new request is in flight (avoids layout jumps). */
    staleData: state.data,
    error: settled ? state.error : undefined,
    loading: fullKey != null && !settled,
    reload,
  };
}
