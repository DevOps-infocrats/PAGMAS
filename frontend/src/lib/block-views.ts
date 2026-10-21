/**
 * The three Block Insights views, in sidebar order. Single source for the sidebar sub-menu and the page.
 * The view lives in `?view=` and belongs to this page only (not a shared filter), so links to GP Insights
 * never carry it; changing the state, block or compare week on this page keeps it (see use-filters).
 */
export const BLOCK_VIEWS = [
  { id: "summary", title: "Summary (KPIs)", short: "Summary (KPIs)", hint: "GPs, fibre route, HOTO and AMC of the block – with the list of AMC GPs" },
  { id: "gp-uptime", title: "GP Uptime Performance", short: "GP Uptime Performance", hint: "Availability bands of the block's AMC GPs – month-wise, week-wise or day by day; the arrow switches table / graph" },
  { id: "olt", title: "OLT Distribution", short: "OLT Distribution", hint: "How many of the block's GPs are connected through each OLT location" },
] as const;

export type BlockViewId = (typeof BLOCK_VIEWS)[number]["id"];
export const BLOCK_VIEW_IDS: string[] = BLOCK_VIEWS.map((v) => v.id);
export const BLOCK_PATH = "/dashboard/block-insights";
/** Opening Block Insights shows the summary. */
export const DEFAULT_BLOCK_VIEW: BlockViewId = "summary";

/** The view id from the URL (?view=), falling back to the summary for a missing / unknown value. */
export function blockViewFrom(value: string | null | undefined): BlockViewId {
  return (BLOCK_VIEW_IDS.includes(value ?? "") ? value : DEFAULT_BLOCK_VIEW) as BlockViewId;
}
