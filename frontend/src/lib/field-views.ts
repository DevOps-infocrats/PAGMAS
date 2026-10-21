/**
 * The Field Team & Escalation views, in sidebar order. Single source for the sidebar sub-menu and the page.
 * The view lives in `?view=` and belongs to this page only (not a shared filter).
 */
export const FIELD_VIEWS = [
  { id: "summary", title: "Summary (KPIs)", short: "Summary (KPIs)", hint: "Team size, contact coverage and down GPs from the Escalation Matrix" },
  { id: "team", title: "Team Directory", short: "Team Directory", hint: "Area managers, FEs, splicers and FRT teams – each counted once – with the districts, blocks and teams they cover" },
  { id: "lookup", title: "Escalation Lookup", short: "Escalation Lookup", hint: "Find a GP and see whom to call, step by step: FRT → Splicer → FE → AM → SHQ SPOC → COH → CBH" },
  { id: "workload", title: "Team Workload", short: "Team Workload", hint: "GPs per FRT team, splicer, FE and AM, with the month-to-date availability of their AMC GPs" },
  { id: "down", title: "Down GPs – Who to Call", short: "Down GPs – Who to Call", hint: "AMC GPs at 0% (or below 90%) month-to-date, with their field team" },
  { id: "gaps", title: "Data Gaps", short: "Data Gaps", hint: "Missing or invalid contacts to be corrected in the Escalation Matrix" },
] as const;

export type FieldViewId = (typeof FIELD_VIEWS)[number]["id"];
export const FIELD_VIEW_IDS: string[] = FIELD_VIEWS.map((v) => v.id);
export const FIELD_PATH = "/dashboard/field-team";
export const DEFAULT_FIELD_VIEW: FieldViewId = "summary";

/** The view id from the URL (?view=), falling back to the summary for a missing / unknown value. */
export function fieldViewFrom(value: string | null | undefined): FieldViewId {
  return (FIELD_VIEW_IDS.includes(value ?? "") ? value : DEFAULT_FIELD_VIEW) as FieldViewId;
}
