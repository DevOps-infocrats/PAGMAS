import type { AdminApi, DashboardApi } from "./contracts";
import { ApiError } from "./errors";
import { httpAdminApi, httpApi } from "./http-client";
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
      getRunIssues: unavailable,
      getRunReport: unavailable,
      getReconciliation: unavailable,
      getEscalationImports: unavailable,
      listUsers: unavailable,
      createUser: unavailable,
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
