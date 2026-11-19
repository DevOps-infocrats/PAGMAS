"use client";

/**
 * Non-Doable GPs in the SME / COH ticket tables: the cases of this ticket the backend hands to the signed-in SME / COH
 * (the same list as the "Non-Doable cases waiting for you" strip – app.tickets.nondoable._visible_cases, only cases
 * handed to them), shown as rows next to the normal GPs. The review itself happens on the case page ("Open ND →").
 */

import Link from "next/link";
import { useApiQuery } from "@/hooks/use-api-query";
import { ndApi, type NdCaseRow } from "@/lib/api";
import { cn } from "@/lib/utils/cn";

const DAY_MS = 86_400_000;
const CLOSED = ["APPROVED", "REJECTED", "WITHDRAWN"];

/** The Non-Doable cases of the ticket handed to this SME / COH (null role = nothing is loaded). `version` reloads them
 * when the ticket changes (a step taken in the strip above, a refresh). */
export function useReviewerNdCases(ticketId: number, role: "SME" | "COH" | null, version: string): NdCaseRow[] {
  const q = useApiQuery(role ? `nd-reviewer:${ticketId}:${role}:${version}` : null, () => ndApi.listCases({ ticket: ticketId, size: 100 }));
  return role ? (q.data?.items ?? []).filter((c) => c.roles.includes(role)) : [];
}

/** Waiting for this SME / COH now. */
export const ndPendingFor = (c: NdCaseRow, role: "SME" | "COH") => c.pendingWith === role && !CLOSED.includes(c.status);

/**
 * One Non-Doable GP as a table row. `statusSpan` = how many columns the status takes (the normal GP's report / review
 * columns); `actionFirst` = the Action column comes before the Waiting column (COH table).
 */
export function NdGpRow({ c, role, nowMs, statusSpan, actionFirst = false }: { c: NdCaseRow; role: "SME" | "COH"; nowMs: number; statusSpan: number; actionFirst?: boolean }) {
  const pending = ndPendingFor(c, role);
  const days = pending && c.updatedAt ? Math.max(0, Math.floor((nowMs - new Date(c.updatedAt).getTime()) / DAY_MS)) : null;
  const waiting = (
    <td className="whitespace-nowrap px-2 py-2.5">
      {days !== null ? (
        <span className={cn("rounded-full px-2 py-0.5 text-[0.71875rem] font-semibold", days > 2 ? "bg-critical-soft text-critical-text" : "bg-muted text-foreground")} title="Days since the case reached you">
          {days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"}`}
        </span>
      ) : (
        <span className="text-[0.75rem] text-muted-foreground">—</span>
      )}
    </td>
  );
  const action = (
    <td className="px-2 py-2">
      <Link
        href={`/dashboard/tickets/non-doable?case=${c.id}`}
        className={cn(
          "inline-flex items-center whitespace-nowrap rounded-md px-2 py-1 text-[0.71875rem] font-semibold",
          pending ? "bg-critical text-white hover:bg-critical/90" : "border border-border text-primary hover:bg-muted",
        )}
        title={pending ? "Open the case – review the E1 / E2 evidence and recommend / forward or return" : "Open the case"}
      >
        Open {c.ref} →
      </Link>
    </td>
  );
  return (
    <tr className={cn("border-b border-border/70 align-top transition-colors last:border-0 hover:bg-muted/40", pending && "bg-critical-soft/15")}>
      <td className={cn("border-l-4 px-3 py-2.5", pending ? "border-l-critical" : "border-l-transparent")} />
      <td className="px-2 py-2.5">
        <span className="font-semibold">{c.gpCode}</span>
        <span className="mt-0.5 block">
          <span className="rounded bg-critical-soft px-1.5 py-0.5 text-[0.625rem] font-semibold text-critical-text">Non-Doable</span>
        </span>
      </td>
      <td className="px-2 py-2.5">
        <span className="block font-medium">{c.gpName ?? "—"}</span>
        <span className="block text-[0.75rem] text-muted-foreground">{c.block ?? "—"}</span>
      </td>
      <td className="px-2 py-2.5">
        <span className="block font-medium">{c.fe ?? "FE not mapped"}</span>
      </td>
      <td colSpan={statusSpan} className="px-2 py-2.5">
        <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold", pending ? "bg-critical-soft text-critical-text" : "bg-muted text-foreground")}>{c.statusLabel}</span>
        <span className="mt-0.5 block text-[0.71875rem] text-muted-foreground">
          {c.ref}
          {c.round > 1 ? ` · round ${c.round}` : ""} · {pending ? `waiting for you (${role})` : c.pendingWith ? `with ${c.pendingWith}` : "closed"} · E1 / E2 evidence and history in the case
        </span>
      </td>
      {actionFirst ? (
        <>
          {action}
          {waiting}
        </>
      ) : (
        <>
          {waiting}
          {action}
        </>
      )}
    </tr>
  );
}
