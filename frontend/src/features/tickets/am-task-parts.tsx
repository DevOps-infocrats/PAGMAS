"use client";

/**
 * Area Manager view of the GP-wise task (User Tickets, AM login only): the work tabs (by review stage) and the summary
 * cards. Display only – who may approve / return what stays in ticket-review.tsx (STEPS) and the backend.
 */

import type { GpStage, TicketTaskGp } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { stageOf } from "./ticket-review";

export type AmTab = "pending" | "field" | "returned" | "approved" | "all";

/** Which work tab a GP is in (by its workflow stage – the same stages as the review badges). */
const BUCKET: Record<GpStage, Exclude<AmTab, "all">> = {
  PENDING_AM: "pending",
  SME_RETURNED: "pending",
  NONE: "field",
  PENDING_FE: "field",
  RETURNED_FRT: "field",
  RETURNED: "returned",
  AM_APPROVED: "approved",
  SME_FORWARDED: "approved",
  COH_RETURNED: "approved",
  LETTER_SUBMITTED: "approved",
  AMC_CONVERTED: "approved",
  ND_APPROVED: "approved",
};

export const amBucket = (g: TicketTaskGp): Exclude<AmTab, "all"> => BUCKET[stageOf(g)] ?? "field";

export const AM_TABS: { key: AmTab; label: string; hint: string }[] = [
  { key: "pending", label: "Approval pending", hint: "Reported by the FE (or verified by the FE from the FRT) – approve or return" },
  { key: "field", label: "With FE / FRT", hint: "Not reported yet, or waiting for the FE's check of the FRT report" },
  { key: "returned", label: "Returned to FE", hint: "Sent back by you – waiting for the FE's correction" },
  { key: "approved", label: "Approved → SME", hint: "Approved by you and further (SME / COH / letter / AMC)" },
  { key: "all", label: "All", hint: "Every GP of the ticket" },
];

/** Area Manager summary: what waits for the AM, what is with the team, and the week's result. */
export function AmSummary({ gps, achieved, target }: { gps: TicketTaskGp[]; achieved: number; target: number }) {
  const n = (k: Exclude<AmTab, "all">) => gps.filter((g) => amBucket(g) === k).length;
  const cards: [string, string, string | undefined, string][] = [
    ["Approval pending", String(n("pending")), "text-warning-text", "waiting for your Approve / Return"],
    ["Returned to FE", String(n("returned")), "text-critical-text", "waiting for the FE's correction"],
    ["Approved → SME", String(n("approved")), "text-good-text", "approved by you (and further)"],
    ["With FE / FRT", String(n("field")), "text-[var(--series-1)]", "not reported yet / FE checking the FRT report"],
    ["Non-Doable open", String(gps.filter((g) => g.ndCase?.open).length), "text-critical-text", "open Non-Doable cases"],
    ["Achieved / Target", `${achieved} / ${target}`, "text-good-text", "GPs achieved this week"],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 border-b border-border px-5 py-3 sm:grid-cols-3 lg:grid-cols-6">
      {cards.map(([label, value, cls, hint]) => (
        <div key={label} className="rounded-lg border border-border px-3 py-2" title={hint}>
          <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className={cn("tabular text-xl font-bold", value !== "0" ? cls : "text-muted-foreground")}>{value}</p>
        </div>
      ))}
    </div>
  );
}
