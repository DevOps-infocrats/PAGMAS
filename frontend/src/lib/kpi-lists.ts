import type { KpiListKind } from "@/lib/api";

/**
 * KPI cards that open a list of the GPs / blocks behind them (Circle Overview → Summary).
 * The page is /dashboard/kpi-list?kind=…; `kind` is a page-local parameter (kept when the state /
 * district / block filters change on that page, never carried to other pages).
 */
export const KPI_LIST_PATH = "/dashboard/kpi-list";

export const KPI_LISTS: Record<KpiListKind, { unit: "gp" | "block"; linkLabel: string }> = {
  "gps-above-98": { unit: "gp", linkLabel: "View GP list" },
  "gps-at-zero": { unit: "gp", linkLabel: "View GP list" },
  "penalty-blocks": { unit: "block", linkLabel: "View block list" },
  "hoto-gps": { unit: "gp", linkLabel: "View GP list" },
  "hoto-blocks": { unit: "block", linkLabel: "View block list" },
  "existing-gps": { unit: "gp", linkLabel: "View GP list" },
  "new-gp-blocks": { unit: "block", linkLabel: "View block list" },
  "na-gps": { unit: "gp", linkLabel: "View GP list" },
  "one-time-up": { unit: "gp", linkLabel: "View GP list" },
  "hoto-pending-gps": { unit: "gp", linkLabel: "View GP list" },
  "removed-gps": { unit: "gp", linkLabel: "View GP list" },
  "amc-plan-month": { unit: "gp", linkLabel: "View GP list" },
  "amc-plan-mtd": { unit: "gp", linkLabel: "View GP list" },
  "amc-achieved-mtd": { unit: "gp", linkLabel: "View GP list" },
  "amc-plan-week": { unit: "gp", linkLabel: "View GP list" },
  "amc-achieved-week": { unit: "gp", linkLabel: "View GP list" },
  "amc-overdue": { unit: "gp", linkLabel: "View GP list" },
};

/**
 * State pages opened from the Circle Overview tables: one page per state, its lists as tabs.
 * `view` = the Circle Overview view whose table opens the page (its Back button returns there).
 */
export const KPI_LIST_GROUPS = {
  comparison: {
    title: "GP details",
    view: "states",
    tabs: [
      { kind: "existing-gps", label: "Existing GPs" },
      { kind: "new-gp-blocks", label: "New GPs (block-wise)" },
    ],
  },
  health: {
    title: "Network health",
    view: "states",
    tabs: [
      { kind: "gps-above-98", label: "GPs >98%" },
      { kind: "gps-at-zero", label: "GPs at 0%" },
      { kind: "na-gps", label: "Not reported (NA)" },
      { kind: "penalty-blocks", label: "Penalty blocks <90%" },
      { kind: "one-time-up", label: "One-time UP (Sept)" },
    ],
  },
  hoto: {
    title: "HOTO details",
    view: "handover",
    tabs: [
      { kind: "hoto-gps", label: "HOTO done GPs" },
      { kind: "hoto-pending-gps", label: "HOTO pending GPs" },
      { kind: "hoto-blocks", label: "HOTO done blocks" },
    ],
  },
  converted: {
    title: "GPs converted to NP / closed",
    view: "handover",
    tabs: [{ kind: "removed-gps", label: "Converted / closed GPs" }],
  },
} as const satisfies Record<string, { title: string; view: "states" | "handover"; tabs: readonly { kind: KpiListKind; label: string }[] }>;
export type KpiListGroup = keyof typeof KPI_LIST_GROUPS;

export function kpiListGroupFrom(value: string | null | undefined): KpiListGroup | null {
  return value && value in KPI_LIST_GROUPS ? (value as KpiListGroup) : null;
}

/** Link to a state page (group) opened from the overview tables: the given / first tab, Back returns to that view. */
export function stateDetailHref(base: string, group: KpiListGroup, kind?: KpiListKind): string {
  const q = `kind=${kind ?? KPI_LIST_GROUPS[group].tabs[0].kind}&group=${group}&from=states`;
  return `${base}${base.includes("?") ? "&" : "?"}${q}`;
}

/** Where a list was opened from – decides the Back button (Circle Overview or that state's Circle Insights). */
export type KpiListOrigin = "overview" | "circle" | "states" | "amc";

/** Link to a list: `base` = hrefTo(KPI_LIST_PATH, filters) of the page that opens it. */
export function kpiListHref(base: string, kind: KpiListKind, from: KpiListOrigin = "overview"): string {
  const q = `kind=${kind}${from === "circle" || from === "amc" ? `&from=${from}` : ""}`;
  return `${base}${base.includes("?") ? "&" : "?"}${q}`;
}

export function kpiListKindFrom(value: string | null | undefined): KpiListKind | null {
  return value && value in KPI_LISTS ? (value as KpiListKind) : null;
}
