"use client";

import { useSearchParams } from "next/navigation";
import { useMeta } from "@/components/providers/data-provider";
import { useFilters, type Filters } from "@/hooks/use-filters";
import { BLOCK_PATH, BLOCK_VIEW_IDS } from "@/lib/block-views";
import { CIRCLE_PATH, CIRCLE_VIEW_IDS } from "@/lib/circle-views";
import { GP_PATH, GP_VIEW_IDS } from "@/lib/gp-views";
import { OVERVIEW_PATH, OVERVIEW_VIEW_IDS } from "@/lib/overview-views";

/**
 * Back buttons of Circle Overview → Circle Insights → Block Insights → GP Insights.
 *
 * A link inside this flow adds `?from=` = the way back, nearest step first, e.g. on a block's Summary opened from
 * Circle Insights → Block-wise GP Count (itself opened from the state's Summary, opened from Circle Overview):
 *   from=circle-blocks.circle-summary.overview-summary
 * Back opens the first step with the rest as its own `from`, so every page on the way keeps its Back button.
 * A Back is shown only for (a) a sub-view opened from its own Summary's "More …" links, (b) a Summary opened from
 * the page one level up. Sidebar / search links carry no `from`, so they show no Back. `from` is a page parameter
 * (kept when the state / block / GP / week changes on the page; see use-filters) – Back then uses the new selection.
 * Navigation only: no data is read or changed.
 */
export type InsightsPage = "overview" | "circle" | "block" | "gp";

const ORDER: InsightsPage[] = ["overview", "circle", "block", "gp"];
const PATH: Record<InsightsPage, string> = { overview: OVERVIEW_PATH, circle: CIRCLE_PATH, block: BLOCK_PATH, gp: GP_PATH };
const VIEW_IDS: Record<InsightsPage, string[]> = { overview: OVERVIEW_VIEW_IDS, circle: CIRCLE_VIEW_IDS, block: BLOCK_VIEW_IDS, gp: GP_VIEW_IDS };
/** Selection levels a page keeps when Back opens it (lower levels are cleared, as that page's own pickers do). */
const CLEAR: Record<InsightsPage, Filters> = {
  overview: { circle: undefined, district: undefined, block: undefined, gp: undefined },
  circle: { district: undefined, block: undefined, gp: undefined },
  block: { gp: undefined },
  gp: {},
};

interface Step {
  page: InsightsPage;
  view: string;
}

const join = (href: string, q: string) => `${href}${href.includes("?") ? "&" : "?"}${q}`;

/** The steps of a `from` value, nearest first; stops at the first one that is not a known page + view. */
function parseFrom(value: string | null): Step[] {
  const steps: Step[] = [];
  for (const seg of (value ?? "").split(".")) {
    const i = seg.indexOf("-");
    const page = seg.slice(0, i) as InsightsPage;
    const view = seg.slice(i + 1);
    if (i < 1 || !ORDER.includes(page) || !VIEW_IDS[page].includes(view)) break;
    steps.push({ page, view });
  }
  return steps;
}

const formatFrom = (steps: Step[]) => steps.map((s) => `${s.page}-${s.view}`).join(".");

export function useInsightsNav(page: InsightsPage, viewId: string) {
  const params = useSearchParams();
  const meta = useMeta();
  const { filters, hrefTo } = useFilters();
  const steps = parseFrom(params.get("from"));
  /** `from` for a link that leaves this page / view (to a sub-view or the page one level down). */
  const forward = formatFrom([{ page, view: viewId }, ...steps]);

  let back: { href: string; label: string } | null = null;
  const [target, ...rest] = steps;
  const parent = ORDER[ORDER.indexOf(page) - 1];
  const ownSummary = target && target.page === page && target.view === "summary" && viewId !== "summary";
  const fromParent = target && target.page === parent && viewId === "summary";
  if (ownSummary || fromParent) {
    let href = join(hrefTo(PATH[target.page], CLEAR[target.page]), `view=${target.view}`);
    if (rest.length) href = join(href, `from=${formatFrom(rest)}`);
    const label = ownSummary
      ? "Summary (KPIs)"
      : target.page === "overview"
        ? "Circle Overview"
        : target.page === "circle"
          ? (meta?.circles.find((c) => c.id === filters.circle)?.name ?? "Circle Insights")
          : `${meta?.blocks.find((b) => b.id === filters.block)?.name ?? "the"} block`;
    back = { href, label: `Back to ${label}` };
  }

  return {
    back,
    /** Adds the way back to a link inside the flow. */
    withFrom: (href: string) => join(href, `from=${forward}`),
  };
}
