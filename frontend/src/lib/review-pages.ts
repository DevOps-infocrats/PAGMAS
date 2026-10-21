/**
 * The five Management Review pages, in slide order. Single source for the sidebar sub-menu and the
 * review page itself; ids match the backend deck sections (backend/app/reports/review_pptx.py).
 */
export const REVIEW_PAGES = [
  { id: "summary", title: "Executive Summary", short: "Executive Summary", hint: "Availability KPIs, AMC & monthly target, executive insights" },
  { id: "targets", title: "Target & Achievement", short: "Target & Achievement", hint: "Circle AMC conversions, monthly conversion plan, weekly closure targets" },
  { id: "blocks-gps", title: "Critical KPI – Blocks & GPs", short: "Critical KPI – Blocks & GPs", hint: "Monthly & weekly performance by circle", perCircle: true },
  { id: "block-network", title: "Block Network Availability & Uptime Performance", short: "Block Network Availability", hint: "Block availability bands by circle", perCircle: true },
  { id: "gp-network", title: "GP Network Availability & Uptime Performance", short: "GP Network Availability", hint: "GP availability bands by circle", perCircle: true },
] as const;

export type ReviewPageId = (typeof REVIEW_PAGES)[number]["id"];
export const REVIEW_PAGE_IDS: string[] = REVIEW_PAGES.map((p) => p.id);
export const REVIEW_PATH = "/dashboard/reports";
/** Opening Management Review shows page 1. */
export const DEFAULT_REVIEW_PAGE: ReviewPageId = "summary";

/** The page id from the URL (?page=), falling back to page 1 for a missing / unknown value. */
export function reviewPageFrom(value: string | null | undefined): ReviewPageId {
  return (REVIEW_PAGE_IDS.includes(value ?? "") ? value : DEFAULT_REVIEW_PAGE) as ReviewPageId;
}
