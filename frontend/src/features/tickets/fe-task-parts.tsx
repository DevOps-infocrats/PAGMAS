"use client";

/**
 * FE view of the GP-wise task (User Tickets, Field Engineer login only): summary cards, the short Target · Achieved ·
 * Gap cell and the GP type tag. Display only – the rules (who reports which GP, Verify / Return) stay in
 * ticket-task.tsx and the backend.
 */

import type { TicketTaskGp } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { ticketDay } from "./ticket-parts";

/** FE summary: what waits for the FE (FRT reports to verify, own GPs to fill, returns). */
export function FeSummary({ gps }: { gps: TicketTaskGp[] }) {
  const n = (p: (g: TicketTaskGp) => boolean) => gps.filter(p).length;
  const frt = (g: TicketTaskGp) => !!g.frtAssigned;
  const cards: [string, number, string | undefined, string][] = [
    ["Verify pending", n((g) => frt(g) && g.frtStage === "PENDING_FE"), "text-warning-text", "FRT submitted – check and verify"],
    ["Returned to FRT", n((g) => frt(g) && g.frtStage === "RETURNED_FRT"), "text-critical-text", "waiting for the FRT's correction"],
    // verified FRT reports + GPs the FE reported itself (own GPs, or an FRT GP the FRT had not reported)
    ["Sent to AM", n((g) => g.frtStage === "FE_VERIFIED" || (!g.frtStage && !!g.gpCategory)), "text-good-text", "verified / reported by you"],
    ["Your GPs to fill", n((g) => !frt(g) && !g.gpCategory), "text-[var(--series-1)]", "GPs without an FRT login"],
    ["Returned by AM", n((g) => g.review === "RETURNED"), "text-critical-text", "correct and send again"],
    ["FRT not filled", n((g) => frt(g) && !g.gpCategory && !g.frtStage), "text-muted-foreground", "FRT has not reported yet – you can fill it yourself"],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 border-b border-border px-5 py-3 sm:grid-cols-3 lg:grid-cols-6">
      {cards.map(([label, value, cls, hint]) => (
        <div key={label} className="rounded-lg border border-border px-3 py-2" title={hint}>
          <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className={cn("tabular text-xl font-bold", value ? cls : "text-muted-foreground")}>{value}</p>
        </div>
      ))}
    </div>
  );
}

/** Target · Achieved · Gap in one short cell (full words in the tooltip). */
export function TagCell({ target, achieved }: { target: number; achieved: number }) {
  const gap = target - achieved;
  return (
    <span className="tabular whitespace-nowrap text-[0.8125rem] font-semibold" title={`Target ${target} · Achieved ${achieved} · Gap ${gap}`}>
      {target} · <span className={cn(achieved >= target && "text-good-text")}>{achieved}</span> ·{" "}
      <span className={gap > 0 ? "text-critical-text" : "text-good-text"}>{gap}</span>
    </span>
  );
}

/** The GP's type as a small tag: Wk = planned this week, Added = added in the field, Pend = carried over. */
export function TypeTag({ g }: { g: TicketTaskGp }) {
  const [label, cls, title] =
    g.kind === "WEEK"
      ? ["Wk", "bg-primary-soft text-primary", g.plannedDate ? `This week – planned ${ticketDay(g.plannedDate)}` : "This week"]
      : g.kind === "ADDED"
        ? ["Added", "bg-muted text-foreground", `Added by ${g.addedBy ?? "the FE"}`]
        : ["Pend", "bg-warning-soft text-warning-text", "Pending from an earlier week"];
  return (
    <span className={cn("rounded px-1.5 py-0.5 text-[0.625rem] font-semibold", cls)} title={title}>
      {label}
    </span>
  );
}
