import type { AdminApi, DashboardApi, EscalationSheetQuery, FieldQuery, KpiListQuery, NonDoableApi, TicketApi } from "./contracts";
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

const fallbackMessage = (status: number) => (status === 503 ? "The data service is not ready yet." : `Request failed (${status})`);
const UNREACHABLE = "Cannot reach the data service. Is the backend running?";

async function errorBody(res: Response): Promise<{ message: string; body?: unknown }> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return { message: body.detail, body };
    return { message: fallbackMessage(res.status), body };
  } catch {
    /* not JSON */
  }
  return { message: fallbackMessage(res.status) };
}

/** Session expired or revoked: go back to the login page, keeping the current location. */
function toLogin(status: number, path: string) {
  if (status !== 401 || typeof window === "undefined" || path.startsWith("/auth/")) return;
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.replace(`${window.location.origin}/login?next=${next}&expired=1`);
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
    throw new ApiError(0, UNREACHABLE);
  }
  toLogin(res.status, path);
  if (!res.ok) {
    const e = await errorBody(res);
    throw new ApiError(res.status, e.message, e.body);
  }
  return res.json() as Promise<T>;
}

/**
 * POST a form with upload progress (fetch cannot report it). Same rules as `request`: same-origin cookie,
 * CSRF header, login redirect on 401 and the backend's `detail` as the error message.
 */
function upload<T>(path: string, body: FormData, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    const token = csrfToken();
    if (token) xhr.setRequestHeader("X-CSRF-Token", token);
    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && e.total > 0) onProgress(Math.min(1, e.loaded / e.total));
      };
    }
    xhr.onerror = () => reject(new ApiError(0, UNREACHABLE));
    xhr.onabort = () => reject(new ApiError(0, "Upload cancelled."));
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON */
      }
      toLogin(xhr.status, path);
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = (data as { detail?: unknown } | null)?.detail;
        reject(new ApiError(xhr.status, typeof detail === "string" ? detail : fallbackMessage(xhr.status)));
        return;
      }
      resolve(data as T);
    };
    xhr.send(body);
  });
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

const sheetQuery = (q: EscalationSheetQuery) => qs({ circle: q.circleId, district: q.districtId, block: q.blockId, search: q.search, page: q.page, page_size: q.pageSize });

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
  getAmcAreaManagers: (week, circle) => request(`/amc-plan/area-managers${qs({ week, circle })}`),
  getFieldSummary: (week) => request(`/field-team/summary${qs({ week })}`),
  getFieldLookup: (q) => request(`/field-team/lookup${fieldQuery(q)}`),
  getEscalationSheet: (q) => request(`/field-team/sheet${sheetQuery(q)}`),
  saveEscalationSheet: (importId, changes) => request("/field-team/sheet", { method: "PATCH", body: JSON.stringify({ importId, changes }) }),
  replaceInEscalationSheet: (body) => request("/field-team/sheet/replace", { method: "POST", body: JSON.stringify(body) }),
  getEscalationSheetEdits: (gpCode) => request(`/field-team/sheet/edits${qs({ gpCode })}`),
  escalationSheetExportUrl: (q) => `${API_BASE}/field-team/sheet/export.xlsx${sheetQuery({ ...q, page: undefined, pageSize: undefined })}`,
  getFieldWorkload: (role, q) => request(`/field-team/workload${qs({ role, week: q.weekId, circle: q.circleId })}`),
  getFieldPeople: (role, q) => request(`/field-team/people${qs({ role, week: q.weekId, circle: q.circleId, search: q.search })}`),
  getFieldDown: (mode, q) => request(`/field-team/down${fieldQuery(q, { mode })}`),
  getFieldGaps: (issue, q) => request(`/field-team/gaps${fieldQuery(q, { issue: issue ?? undefined })}`),
  getAmcConversion: (p) => request(`/amc-conversion${qs({ week: p.weekId, compare: p.compareWeekId })}`),
};

export const httpAdminApi: AdminApi = {
  uploadWorkbook: (file, onProgress) => {
    const body = new FormData();
    body.append("file", file);
    return upload("/ingestion/upload", body, onProgress);
  },
  previewUpload: (file, kind, onProgress) => {
    const body = new FormData();
    body.append("kind", kind);
    body.append("file", file);
    return upload("/ingestion/preview", body, onProgress);
  },
  confirmUpload: (token) => request("/ingestion/confirm", { method: "POST", body: JSON.stringify({ token }) }),
  discardUpload: (token) => request(`/ingestion/preview/${encodeURIComponent(token)}`, { method: "DELETE" }),
  getRunIssues: (id, p = {}) => request(`/ingestion/runs/${encodeURIComponent(id)}/issues${qs({ severity: p.severity, code: p.code, page: p.page })}`),
  runIssuesXlsxUrl: (id, p = {}) => `${API_BASE}/ingestion/runs/${encodeURIComponent(id)}/issues.xlsx${qs({ severity: p.severity, code: p.code })}`,
  getRunReport: (id) => request(`/ingestion/runs/${encodeURIComponent(id)}/report`),
  getEscalationImports: () => request("/ingestion/escalation"),
  checkColumns: (source) => {
    if ("file" in source) {
      const body = new FormData();
      body.append("file", source.file);
      return upload("/ingestion/column-check", body);
    }
    return "runId" in source
      ? request(`/ingestion/runs/${encodeURIComponent(source.runId)}/column-check`)
      : request(`/ingestion/escalation/${encodeURIComponent(source.escalationId)}/column-check`);
  },
  getColumnMap: () => request("/ingestion/column-map"),
  addColumnNames: (body) => request("/ingestion/column-map", { method: "POST", body: JSON.stringify(body) }),
  removeColumnName: (body) => request("/ingestion/column-map/remove", { method: "POST", body: JSON.stringify(body) }),
  listPlanFiles: () => request("/plan-files"),
  savePlanFile: (name, data) => request(`/plan-files/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ data }) }),
  getPlanFileHistory: (name) => request(`/plan-files/${encodeURIComponent(name)}/history`),
  reprocessRun: (id) => request(`/ingestion/runs/${encodeURIComponent(id)}/reprocess`, { method: "POST" }),
  reprocessEscalation: (id) => request(`/ingestion/escalation/${encodeURIComponent(id)}/reprocess`, { method: "POST" }),
  getReconciliation: () => request("/ingestion/reconciliation"),
  listUsers: () => request("/users"),
  createUser: (body) => request("/users", { method: "POST", body: JSON.stringify(body) }),
  updateUser: (id, body) => request(`/users/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  importUsers: (file, dryRun) => {
    const body = new FormData();
    body.append("file", file);
    return upload(`/users/import?dryRun=${dryRun ? "true" : "false"}`, body);
  },
  getUserLocations: () => request("/users/locations"),
  getMailStatus: () => request("/mail/status"),
  getMailOptions: () => request("/mail/options"),
  sendTestMail: (to) => request("/mail/test", { method: "POST", body: JSON.stringify({ to }) }),
  listMailTemplates: () => request("/mail/templates"),
  createMailTemplate: (body) => request("/mail/templates", { method: "POST", body: JSON.stringify(body) }),
  updateMailTemplate: (id, body) => request(`/mail/templates/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  resetMailTemplate: (id) => request(`/mail/templates/${id}/reset`, { method: "POST" }),
  deleteMailTemplate: (id) => request(`/mail/templates/${id}/delete`, { method: "POST" }),
  previewMailTemplate: (body) => request("/mail/templates/preview", { method: "POST", body: JSON.stringify(body) }),
  listMailConfigs: () => request("/mail/configs"),
  createMailConfig: (body) => request("/mail/configs", { method: "POST", body: JSON.stringify(body) }),
  updateMailConfig: (id, body) => request(`/mail/configs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  setMailConfigEnabled: (id, enabled) => request(`/mail/configs/${id}/enabled`, { method: "POST", body: JSON.stringify({ enabled }) }),
  deleteMailConfig: (id) => request(`/mail/configs/${id}/delete`, { method: "POST" }),
  previewMailRecipients: (id) => request(`/mail/configs/${id}/recipients`),
  listMailRuns: () => request("/mail/runs"),
};

export const httpTicketApi: TicketApi = {
  getKpis: (scope) => request(`/tickets/kpis${qs({ scope })}`),
  list: (q) =>
    request(
      `/tickets${qs({ scope: q.scope, search: q.search, status: q.status, priority: q.priority, date_from: q.dateFrom, date_to: q.dateTo, circle: q.circle, areaManager: q.areaManager, week: q.week, gp: q.gp, progressDate: q.progressDate, page: q.page, page_size: q.pageSize })}`,
    ),
  get: (id) => request(`/tickets/${id}`),
  listAssignees: () => request("/tickets/assignees"),
  create: (body) => request("/tickets", { method: "POST", body: JSON.stringify(body) }),
  getDirectory: (circle, week) => request(`/tickets/directory${qs({ circle: circle ?? undefined, week })}`),
  getFilterOptions: () => request("/tickets/filter-options"),
  resendEmail: (id, recipientId) => request(`/tickets/${id}/recipients/${recipientId}/email`, { method: "POST" }),
  start: (id) => request(`/tickets/${id}/start`, { method: "POST" }),
  submit: (id, description, files, onProgress) => {
    const body = new FormData();
    body.append("description", description);
    for (const f of files) body.append("attachments", f, f.name);
    return upload(`/tickets/${id}/submit`, body, onProgress);
  },
  close: (id, comment, force) => request(`/tickets/${id}/close`, { method: "POST", body: JSON.stringify({ comment: comment || null, force: !!force }) }),
  remove: (id, reason) => request(`/tickets/${id}`, { method: "DELETE", body: JSON.stringify({ reason: reason || null }) }),
  getShareContacts: (id) => request(`/tickets/${id}/share-contacts`),
  share: (id, recipients, remark) => request(`/tickets/${id}/share`, { method: "POST", body: JSON.stringify({ recipients, remark }) }),
  requestChanges: (id, comment) => request(`/tickets/${id}/request-changes`, { method: "POST", body: JSON.stringify({ comment }) }),
  getNotifications: () => request("/tickets/notifications"),
  markNotificationsRead: () => request("/tickets/notifications/read", { method: "POST" }),
  attachmentUrl: (id, inline) => `${API_BASE}/tickets/attachments/${id}${inline ? "?inline=true" : ""}`,
  getTaskAreaManagers: (week) => request(`/tickets/task/area-managers${qs({ week })}`),
  getTaskPreview: (am, week, circle) => request(`/tickets/task/preview${qs({ am, week, circle })}`),
  submitProgress: (id, items, note) => request(`/tickets/${id}/progress`, { method: "POST", body: JSON.stringify({ items, note: note || null }) }),
  submitProgressForm: (id, items, note, proofs, onProgress, newGps) => {
    const body = new FormData();
    body.append("payload", JSON.stringify({ items, newGps: newGps ?? [], note: note || null }));
    for (const p of proofs) {
      body.append("proofs", p.file, p.file.name);
      body.append("proofGps", String(p.taskGpId));
    }
    return upload(`/tickets/${id}/progress-form`, body, onProgress);
  },
  getReviewContacts: (id, role) => request(`/tickets/${id}/review-contacts${qs({ role })}`),
  reviewGps: (id, body) => request(`/tickets/${id}/review`, { method: "POST", body: JSON.stringify(body) }),
  progressFileUrl: (id, inline) => `${API_BASE}/tickets/progress-files/${id}${inline ? "?inline=true" : ""}`,
  getGpMonitorSummary: (f, basis) => request(`/tickets/gp-monitor/summary${qs({ ...f, basis })}`),
  listGpMonitor: (q) =>
    request(`/tickets/gp-monitor${qs({ ...q, desc: q.desc === undefined ? undefined : String(q.desc), page_size: q.pageSize, pageSize: undefined })}`),
  getGpMonitorDetail: (gpCode) => request(`/tickets/gp-monitor/gps/${encodeURIComponent(gpCode)}`),
  taskWorkbookUrl: (id, kind) => `${API_BASE}/tickets/${id}/task/${kind}.xlsx`,
};

export const httpNdApi: NonDoableApi = {
  getSummary: () => request("/nondoable/summary"),
  listCases: (q) => request(`/nondoable/cases${qs({ status: q.status, q: q.q, mine: q.mine ? "true" : undefined, ticket: q.ticket, page: q.page, size: q.size })}`),
  getCase: (id) => request(`/nondoable/cases/${id}`),
  getContacts: (id, role) => request(`/nondoable/cases/${id}/contacts${qs({ role })}`),
  submitForm: (id, kind, data, files, revisit, onProgress) => {
    const body = new FormData();
    body.append("payload", JSON.stringify(data));
    if (revisit) body.append("kind", revisit);
    for (const f of files.evidence) body.append("evidence", f, f.name);
    for (const f of files.photos) body.append("photos", f, f.name);
    return upload(`/nondoable/cases/${id}/${kind}`, body, onProgress);
  },
  act: (id, body) => request(`/nondoable/cases/${id}/action`, { method: "POST", body: JSON.stringify(body) }),
  fileUrl: (id, inline) => `${API_BASE}/nondoable/files/${id}${inline ? "?inline=true" : ""}`,
  listMgg: () => request("/nondoable/mgg"),
  addMgg: (userId) => request("/nondoable/mgg", { method: "POST", body: JSON.stringify({ userId }) }),
  removeMgg: (userId) => request(`/nondoable/mgg/${userId}/remove`, { method: "POST" }),
};