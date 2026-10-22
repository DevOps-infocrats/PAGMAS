/**
 * The three Circle Overview views, in sidebar order. Single source for the sidebar sub-menu and the overview
 * page. The view lives in `?view=` and belongs to this page only: it is not one of the shared filters
 * (circle / district / block / gp / week / compare), so links to Circle, Block and GP Insights never carry it.
 */
export const OVERVIEW_VIEWS = [
  { id: "summary", title: "Summary (KPIs)", short: "Summary (KPIs)", hint: "Network scope, handover & AMC, uptime and non-AMC GPs" },
  { id: "states", title: "States & Network Health", short: "States & Network Health", hint: "Month-to-date network health of each state" },
  { id: "handover", title: "Handover & Scope", short: "Handover & Scope", hint: "HOTO completion and GPs that left the scope" },
] as const;

export type OverviewViewId = (typeof OVERVIEW_VIEWS)[number]["id"];
export const OVERVIEW_VIEW_IDS: string[] = OVERVIEW_VIEWS.map((v) => v.id);
export const OVERVIEW_PATH = "/dashboard";
/** Opening Circle Overview shows the summary. */
export const DEFAULT_OVERVIEW_VIEW: OverviewViewId = "summary";

/** The view id from the URL (?view=), falling back to the summary for a missing / unknown value. */
export function overviewViewFrom(value: string | null | undefined): OverviewViewId {
  return (OVERVIEW_VIEW_IDS.includes(value ?? "") ? value : DEFAULT_OVERVIEW_VIEW) as OverviewViewId;
}
