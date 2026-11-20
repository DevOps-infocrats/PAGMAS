"use client";

import { useSyncExternalStore } from "react";
import { useSession } from "@/components/providers/session-provider";
import type { PageKey, Permissions } from "@/lib/api";

/**
 * Roles & Access in the dashboard: which pages the signed-in user's role shows on this device, and where a sign-in
 * lands. The server enforces the same pages on their data (backend app.security.roles.require_page); this only hides
 * menu entries and pages. A phone is a touch device (same rule as the FRT camera).
 */

export const PAGE_HREF: Record<PageKey, string> = {
  overview: "/dashboard",
  "circle-insights": "/dashboard/circle-insights",
  "block-insights": "/dashboard/block-insights",
  "gp-insights": "/dashboard/gp-insights",
  "amc-conversion": "/dashboard/amc-conversion",
  "field-team": "/dashboard/field-team",
  reports: "/dashboard/reports",
  "tickets-user": "/dashboard/tickets/user",
  "tickets-nondoable": "/dashboard/tickets/non-doable",
};

/** The Circle Overview KPI drill-down list (/dashboard/kpi-list) opens from the overview and the insights pages */
const INSIGHTS: PageKey[] = ["overview", "circle-insights", "block-insights", "gp-insights"];

/** The role page a dashboard path belongs to: a page key, "kpi-list", or null (admin pages / settings: own guard). */
export function pageOfPath(pathname: string): PageKey | "kpi-list" | null {
  if (pathname === "/dashboard" || pathname === "/dashboard/") return "overview";
  if (pathname.startsWith("/dashboard/kpi-list")) return "kpi-list";
  const hit = (Object.entries(PAGE_HREF) as [PageKey, string][]).find(([k, href]) => k !== "overview" && (pathname === href || pathname.startsWith(`${href}/`)));
  return hit ? hit[0] : null;
}

/** Whether the role shows the page on this device (no permissions = every page, as before roles). */
export function canSee(perm: Permissions | undefined, key: PageKey | "kpi-list" | null, phone: boolean): boolean {
  if (!perm || perm.all || key === null) return true;
  const keys = key === "kpi-list" ? INSIGHTS : [key];
  return keys.some((k) => (phone ? perm.pages[k]?.phone : perm.pages[k]?.laptop));
}

/** Where a sign-in (or a page the role does not show) lands on this device. */
export function homeHref(perm: Permissions | undefined, phone: boolean): string {
  if (!perm || perm.all) return "/dashboard";
  const start = phone ? perm.phoneHome : perm.laptopHome;
  if (start && canSee(perm, start, phone)) return PAGE_HREF[start];
  const first = (Object.keys(PAGE_HREF) as PageKey[]).find((k) => canSee(perm, k, phone));
  return first ? PAGE_HREF[first] : "/dashboard";
}

const PHONE_QUERY = "(pointer: coarse)";
const subscribePhone = (cb: () => void) => {
  const m = window.matchMedia(PHONE_QUERY);
  m.addEventListener("change", cb);
  return () => m.removeEventListener("change", cb);
};
/** true on a touch device (phone / tablet) */
export const useIsPhone = () => useSyncExternalStore(subscribePhone, () => window.matchMedia(PHONE_QUERY).matches, () => false);

/** The signed-in user's page access on this device. */
export function usePageAccess() {
  const { session, loading } = useSession();
  const phone = useIsPhone();
  const perm = session?.permissions;
  return {
    loading,
    phone,
    roleName: perm?.roleName ?? null,
    can: (key: PageKey | "kpi-list" | null) => canSee(perm, key, phone),
    home: homeHref(perm, phone),
  };
}
