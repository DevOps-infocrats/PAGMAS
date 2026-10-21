/**
 * The AMC Conversion Plan vs Execution views, in sidebar order. Single source for the sidebar sub-menu and the page.
 * The view lives in `?view=` and belongs to this page only (not a shared filter).
 */
export const AMC_VIEWS = [
  { id: "summary", title: "Summary (KPIs)", short: "Summary (KPIs)", hint: "Month, month-to-date and week target vs achieved – GP-wise plan of the master data file" },
  { id: "monthly", title: "Monthly Plan vs Execution", short: "Monthly Plan vs Execution", hint: "Month-wise target vs achieved – target from Planned Date (or the targets file until that month's data arrives), achieved from Ach Date" },
  { id: "weekly", title: "Weekly Plan vs Execution", short: "Weekly Plan vs Execution", hint: "Week-wise (Fri–Thu) target (Planned Date) vs achieved (Ach Date) – GP-wise plan of the master data file" },
  { id: "current", title: "Current Month Detail", short: "Current Month Detail", hint: "Projection, gap and pending scope – as in Management Review → Target & Achievement" },
] as const;

export type AmcViewId = (typeof AMC_VIEWS)[number]["id"];
export const AMC_VIEW_IDS: string[] = AMC_VIEWS.map((v) => v.id);
export const AMC_PATH = "/dashboard/amc-conversion";
export const DEFAULT_AMC_VIEW: AmcViewId = "summary";

/** The view id from the URL (?view=), falling back to the summary for a missing / unknown value. */
export function amcViewFrom(value: string | null | undefined): AmcViewId {
  return (AMC_VIEW_IDS.includes(value ?? "") ? value : DEFAULT_AMC_VIEW) as AmcViewId;
}
