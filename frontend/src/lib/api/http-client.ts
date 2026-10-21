import type { AdminApi, DashboardApi, FieldQuery, KpiListQuery } from "./contracts";
import { ApiError } from "./errors";

/**
 * FastAPI client. Requests go to the same origin (`/api/v1/...`) and Next.js
 * rewrites them to the backend (see next.config.ts), so the session cookie is
 * first-party and httpOnly. State-changing calls send the CSRF token.
 */
export const API_BASE = "/api/v1";
const CSRF_COOKIE = "pratap_csrf";

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${CSRF_COOKIE}=`))
    ?.slice(CSRF_COOKIE.length + 1);
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* not JSON */
  }
  return res.status === 503 ? "The data service is not ready yet." : `Request failed (${res.status})`;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && init.body !== undefined) headers.set("Content-Type", "application/json");
  if (method !== "GET") {
    const token = csrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, method, headers, credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new ApiError(0, "Cannot reach the data service. Is the backend running?");
  }
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    // Session expired or revoked: go back to the login page, keeping the current location.
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.replace(`${window.location.origin}/login?next=${next}&expired=1`);
  }
  if (!res.ok) throw new ApiError(res.status, await errorMessage(res));
  return res.json() as Promise<T>;
}

const qs = (params: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const kpiListQuery = (q: KpiListQuery) =>
  qs({ week: q.weekId, circle: q.circleId, district: q.districtId, block: q.blockId, search: q.search, sort: q.sort, page: q.page, page_size: q.pageSize });

export const reportQuery = (p: { weekId: string; compareWeekId: string; circleId?: string; districtId?: string; blockId?: string }) =>
  qs({ week: p.weekId, compare: p.compareWeekId, circle: p.circleId, district: p.districtId, block: p.blockId });

const fieldQuery = (q: FieldQuery, extra: Record<string, string | undefined> = {}) =>
  qs({ ...extra, week: q.weekId, circle: q.circleId, district: q.districtId, block: q.blockId, search: q.search, page: q.page });

export const httpApi: DashboardApi = {
  getMeta: () => request("/meta"),
  getOverview: (p) => request(`/overview${qs({ week: p.weekId, compare: p.compareWeekId })}`),
  getCircleInsights: (id, p) => request(`/circles/${encodeURIComponent(id)}/insights${qs({ week: p.weekId, compare: p.compareWeekId })}`),
  getBlockInsights: (id, p) => request(`/blocks/${encodeURIComponent(id)}/insights${qs({ week: p.weekId, compare: p.compareWeekId })}`),
  getGpDetail: (id, week) => request(`/gps/${encodeURIComponent(id)}${qs({ week })}`),
  listGps: (q) =>
    request(`/gps${qs({ circle: q.circleId, district: q.districtId, block: q.blockId, week: q.weekId, search: q.search, page: q.page, page_size: q.pageSize })}`),
  search: (query) => request(`/search${qs({ q: query })}`),
  getWeeklyReport: (p) => request(`/reports/weekly${reportQuery(p)}`),
  getManagementReview: (p) => request(`/reviews/management${qs({ week: p.weekId, compare: p.compareWeekId })}`),
  getIngestionRuns: () => request("/ingestion/runs"),
  retryIngestion: (id) => request(`/ingestion/runs/${encodeURIComponent(id)}/retry`, { method: "POST" }),
  getNotifications: (week) => request(`/notifications${qs({ week })}`),
  getKpiList: (kind, q) => request(`/kpi-lists/${encodeURIComponent(kind)}${kpiListQuery(q)}`),
  getAmcPlanSummary: (week) => request(`/amc-plan/summary${qs({ week })}`),
  getAmcPlanTimeline: (week) => request(`/amc-plan/timeline${qs({ week })}`),
  getFieldSummary: (week) => request(`/field-team/summary${qs({ week })}`),
  getFieldLookup: (q) => request(`/field-team/lookup${fieldQuery(q)}`),
  getFieldWorkload: (role, q) => request(`/field-team/workload${qs({ role, week: q.weekId, circle: q.circleId })}`),
  getFieldPeople: (role, q) => request(`/field-team/people${qs({ role, week: q.weekId, circle: q.circleId, search: q.search })}`),
  getFieldDown: (mode, q) => request(`/field-team/down${fieldQuery(q, { mode })}`),
  getFieldGaps: (issue, q) => request(`/field-team/gaps${fieldQuery(q, { issue: issue ?? undefined })}`),
  getAmcConversion: (p) => request(`/amc-conversion${qs({ week: p.weekId, compare: p.compareWeekId })}`),
};

export const httpAdminApi: AdminApi = {
  uploadWorkbook: (file) => {
    const body = new FormData();
    body.append("file", file);
    return request("/ingestion/upload", { method: "POST", body });
  },
  getRunIssues: (id, p = {}) => request(`/ingestion/runs/${encodeURIComponent(id)}/issues${qs({ severity: p.severity, code: p.code, page: p.page })}`),
  getRunReport: (id) => request(`/ingestion/runs/${encodeURIComponent(id)}/report`),
  getEscalationImports: () => request("/ingestion/escalation"),
  getReconciliation: () => request("/ingestion/reconciliation"),
  listUsers: () => request("/users"),
  createUser: (body) => request("/users", { method: "POST", body: JSON.stringify(body) }),
  updateUser: (id, body) => request(`/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
};
