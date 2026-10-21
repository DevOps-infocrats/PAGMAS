/**
 * The two GP Insights views, in sidebar order. Single source for the sidebar sub-menu and the page.
 * The view lives in `?view=` and belongs to this page only (not a shared filter); changing the state,
 * district, block or GP on this page keeps it (see use-filters).
 */
export const GP_VIEWS = [
  { id: "summary", title: "Summary (KPIs)", short: "Summary (KPIs)", hint: "Location, handover, AMC, fibre and availability of the Gram Panchayat" },
  { id: "gp-uptime", title: "GP Uptime Performance", short: "GP Uptime Performance", hint: "Days this GP spent in each availability band – month-wise, week-wise or day by day; the arrow switches table / graph" },
] as const;

export type GpViewId = (typeof GP_VIEWS)[number]["id"];
export const GP_VIEW_IDS: string[] = GP_VIEWS.map((v) => v.id);
export const GP_PATH = "/dashboard/gp-insights";
/** Opening GP Insights shows the summary. */
export const DEFAULT_GP_VIEW: GpViewId = "summary";

/** The view id from the URL (?view=), falling back to the summary for a missing / unknown value. */
export function gpViewFrom(value: string | null | undefined): GpViewId {
  return (GP_VIEW_IDS.includes(value ?? "") ? value : DEFAULT_GP_VIEW) as GpViewId;
}
