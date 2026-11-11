import type { AdminApi, DashboardApi, NonDoableApi, TicketApi } from "./contracts";
import { ApiError } from "./errors";
import { httpAdminApi, httpApi, httpNdApi, httpTicketApi } from "./http-client";
import { mockApi } from "./mock-client";

export * from "./contracts";
export { ApiError } from "./errors";

/**
 * `live` (default) talks to the FastAPI backend through the Next.js /api rewrite.
 * `mock` serves the generated DEMO dataset without any backend (UI development only).
 */
export const API_MODE: "mock" | "live" = process.env.NEXT_PUBLIC_API_MODE === "mock" ? "mock" : "live";
export const IS_LIVE = API_MODE === "live";

export const api: DashboardApi = IS_LIVE ? httpApi : mockApi;

const unavailable = () => Promise.reject(new ApiError(501, "Not available in demo mode – connect the backend (NEXT_PUBLIC_API_MODE=live)."));

export const adminApi: AdminApi = IS_LIVE
  ? httpAdminApi
  : {
      uploadWorkbook: unavailable,
      previewUpload: unavailable,
      confirmUpload: unavailable,
      discardUpload: unavailable,
      getRunIssues: unavailable,
      runIssuesXlsxUrl: () => "#",
      getRunReport: unavailable,
      getReconciliation: unavailable,
      getEscalationImports: unavailable,
      checkColumns: unavailable,
      getColumnMap: unavailable,
      addColumnNames: unavailable,
      removeColumnName: unavailable,
      listPlanFiles: unavailable,
      savePlanFile: unavailable,
      getPlanFileHistory: unavailable,
      reprocessRun: unavailable,
      reprocessEscalation: unavailable,
      listUsers: unavailable,
      createUser: unavailable,
      importUsers: unavailable,
      updateUser: unavailable,
      getUserLocations: unavailable,
      getMailStatus: unavailable,
      getMailOptions: unavailable,
      sendTestMail: unavailable,
      listMailTemplates: unavailable,
      createMailTemplate: unavailable,
      updateMailTemplate: unavailable,
      resetMailTemplate: unavailable,
      deleteMailTemplate: unavailable,
      previewMailTemplate: unavailable,
      listMailConfigs: unavailable,
      createMailConfig: unavailable,
      updateMailConfig: unavailable,
      setMailConfigEnabled: unavailable,
      deleteMailConfig: unavailable,
      previewMailRecipients: unavailable,
      listMailRuns: unavailable,
    };

/** Ticket Management (live backend only). */
export const ticketApi: TicketApi = IS_LIVE
  ? httpTicketApi
  : {
      getKpis: unavailable,
      list: unavailable,
      get: unavailable,
      listAssignees: unavailable,
      create: unavailable,
      getDirectory: unavailable,
      getFilterOptions: unavailable,
      resendEmail: unavailable,
      start: unavailable,
      submit: unavailable,
      close: unavailable,
      remove: unavailable,
      getShareContacts: unavailable,
      share: unavailable,
      requestChanges: unavailable,
      getNotifications: unavailable,
      markNotificationsRead: unavailable,
      attachmentUrl: () => "#",
      getTaskAreaManagers: unavailable,
      getTaskPreview: unavailable,
      submitProgress: unavailable,
      submitProgressForm: unavailable,
      reviewGps: unavailable,
      getReviewContacts: unavailable,
      progressFileUrl: () => "#",
      getGpMonitorSummary: unavailable,
      listGpMonitor: unavailable,
      getGpMonitorDetail: unavailable,
      taskWorkbookUrl: () => "#",
    };

/** Non-Doable GP exception workflow (live backend only). */
export const ndApi: NonDoableApi = IS_LIVE
  ? httpNdApi
  : {
      getSummary: unavailable,
      listCases: unavailable,
      getCase: unavailable,
      getContacts: unavailable,
      submitForm: unavailable,
      act: unavailable,
      fileUrl: () => "#",
      listMgg: unavailable,
      addMgg: unavailable,
      removeMgg: unavailable,
    };