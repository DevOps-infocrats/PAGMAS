/**
 * The five Circle Insights views, in sidebar order. Single source for the sidebar sub-menu and the page.
 * The view lives in `?view=` and belongs to this page only (not a shared filter), so links to Block / GP
 * Insights never carry it; changing the state or week on this page keeps it (see use-filters).
 */
export const CIRCLE_VIEWS = [
  { id: "summary", title: "Summary (KPIs)", short: "Summary (KPIs)", hint: "Districts, blocks, GPs, HOTO, AMC and RKM of the state" },
  { id: "blocks", title: "Block-wise GP Count", short: "Block-wise GP Count", hint: "How GPs are spread across the blocks of the state · select a block to open it" },
  { id: "hoto", title: "HOTO / AMC Status", short: "HOTO / AMC Status", hint: "Handover and AMC progress against the target" },
  { id: "gp-uptime", title: "GP Uptime Performance", short: "GP Uptime Performance", hint: "Availability bands of AMC GPs – month-wise, week-wise or day by day; the arrow switches table / graph" },
  { id: "block-uptime", title: "Block Uptime Performance", short: "Block Uptime Performance", hint: "Availability bands of blocks – month-wise, week-wise or day by day; the arrow switches table / graph" },
] as const;

export type CircleViewId = (typeof CIRCLE_VIEWS)[number]["id"];
export const CIRCLE_VIEW_IDS: string[] = CIRCLE_VIEWS.map((v) => v.id);
export const CIRCLE_PATH = "/dashboard/circle-insights";
/** Opening Circle Insights shows the summary. */
export const DEFAULT_CIRCLE_VIEW: CircleViewId = "summary";

/** The view id from the URL (?view=), falling back to the summary for a missing / unknown value. */
export function circleViewFrom(value: string | null | undefined): CircleViewId {
  return (CIRCLE_VIEW_IDS.includes(value ?? "") ? value : DEFAULT_CIRCLE_VIEW) as CircleViewId;
}
