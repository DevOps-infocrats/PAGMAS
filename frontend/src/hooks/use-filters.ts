"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import { useMeta } from "@/components/providers/data-provider";
import { useNavigationProgress } from "@/components/layout/navigation-progress";

/**
 * Global selection lives in the URL so it survives navigation, refreshes and
 * can be shared: ?circle=&district=&block=&gp=&week=&compare=
 */
export interface Filters {
  circle?: string;
  district?: string;
  block?: string;
  gp?: string;
  week?: string;
  compare?: string;
}

const KEYS: (keyof Filters)[] = ["circle", "district", "block", "gp", "week", "compare"];
/** Page-local section parameters, kept when filters change on the same page (never carried to other pages):
 *  Circle Overview / Insights ?view=, Management Review ?page=, KPI list ?kind= & ?from= & ?group=,
 *  Field Team & Escalation ?role=. */
const PAGE_SECTION_KEYS = ["view", "page", "kind", "from", "group", "role"] as const;
/** Changing a level clears everything below it. */
const CHILDREN: Partial<Record<keyof Filters, (keyof Filters)[]>> = {
  circle: ["district", "block", "gp"],
  district: ["block", "gp"],
  block: ["gp"],
};

export function buildHref(path: string, filters: Filters): string {
  const p = new URLSearchParams();
  for (const k of KEYS) {
    const v = filters[k];
    if (v) p.set(k, v);
  }
  const s = p.toString();
  return s ? `${path}?${s}` : path;
}

export function useFilters() {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const meta = useMeta();
  const { start } = useNavigationProgress();

  const raw: Filters = useMemo(() => {
    const f: Filters = {};
    for (const k of KEYS) {
      const v = params.get(k);
      if (v) f[k] = v;
    }
    return f;
  }, [params]);

  /** Resolved week + comparison week (defaults: latest vs the week before it). */
  const period = useMemo(() => {
    if (!meta) return null;
    const ids = meta.weeks.map((w) => w.id);
    const weekId = raw.week && ids.includes(raw.week) ? raw.week : meta.latestWeekId;
    const idx = ids.indexOf(weekId);
    const fallbackCompare = ids[Math.max(0, idx - 1)];
    const compareWeekId = raw.compare && ids.includes(raw.compare) ? raw.compare : fallbackCompare;
    return {
      weekId,
      compareWeekId,
      week: meta.weeks[idx],
      compareWeek: meta.weeks.find((w) => w.id === compareWeekId)!,
    };
  }, [meta, raw.week, raw.compare]);

  /** Href to another page that keeps the current selection (plus overrides). */
  const hrefTo = useCallback((path: string, overrides: Filters = {}) => buildHref(path, { ...raw, ...overrides }), [raw]);

  const navigate = useCallback(
    (path: string, overrides: Filters = {}) => {
      start();
      router.push(buildHref(path, { ...raw, ...overrides }));
    },
    [raw, router, start],
  );

  /** Updates filters on the current page, clearing dependent levels. */
  const setFilters = useCallback(
    (patch: Filters) => {
      const next: Filters = { ...raw };
      for (const k of Object.keys(patch) as (keyof Filters)[]) {
        if (patch[k] !== raw[k]) for (const child of CHILDREN[k] ?? []) if (!(child in patch)) delete next[child];
        next[k] = patch[k];
      }
      // Same page: keep the section it shows (Circle Overview ?view=, Management Review ?page=).
      const own = new URLSearchParams();
      for (const k of PAGE_SECTION_KEYS) {
        const v = params.get(k);
        if (v) own.set(k, v);
      }
      const href = buildHref(pathname, next);
      const extra = own.toString();
      router.replace(extra ? `${href}${href.includes("?") ? "&" : "?"}${extra}` : href, { scroll: false });
    },
    [raw, router, pathname, params],
  );

  return { filters: raw, period, hrefTo, navigate, setFilters };
}
