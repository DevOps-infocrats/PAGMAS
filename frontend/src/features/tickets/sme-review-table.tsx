"use client";

/**
 * SME view of a GP-wise task (User Tickets, SME login only – the COH keeps SmeGpTable): the GPs the Area Manager
 * approved and forwarded to this SME, in work tabs (pending first), with the field report, the AM's approval, both
 * proofs, the waiting time and the row's Forward → COH / Back to AM. The GP detail (all sections, history, single
 * review) opens from the GP code / Details. Who may do which step stays in ticket-review.tsx (canStep) and the backend.
 */

import { CheckCircle2, Undo2 } from "lucide-react";
import { useState } from "react";
import { Input } from "@/components/ui/primitives";
import type { GpReviewAction, GpReviewRole, NdCaseRow, TicketDetail, TicketTaskGp } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { TypeTag } from "./fe-task-parts";
import { FrtProofChips } from "./frt-task-parts";
import { GpCategoryBadge } from "./gp-category";
import { GpDetailDialog } from "./gp-detail";
import { NdGpRow, ndPendingFor } from "./nd-gp-rows";
import { ticketDay, type Notice } from "./ticket-parts";
import { REVIEW_STAGE, ReviewDialog, canStep, stageOf } from "./ticket-review";

type SmeTab = "nd" | "pending" | "coh" | "forwarded" | "back" | "all";

/** Which tab a GP is in (by its review state). */
const tabOf = (g: TicketTaskGp): Exclude<SmeTab, "all"> | null =>
  g.review === "AM_APPROVED"
    ? "pending"
    : g.review === "COH_RETURNED"
      ? "coh"
      : g.review === "SME_FORWARDED" || g.review === "LETTER_SUBMITTED" || g.review === "AMC_CONVERTED"
        ? "forwarded"
        : g.review === "SME_RETURNED"
          ? "back"
          : null;

const TABS: { key: SmeTab; label: string; hint: string }[] = [
  { key: "pending", label: "Pending your review", hint: "Approved by the Area Manager – review and forward to the COH, or send back" },
  { key: "coh", label: "Returned by COH", hint: "Sent back to you by the COH – review again" },
  { key: "forwarded", label: "Forwarded to COH", hint: "Reviewed by you and further (letter / AMC)" },
  { key: "back", label: "Sent back to AM", hint: "Sent back by you – waiting for the Area Manager" },
  { key: "nd", label: "Non-Doable", hint: "Non-Doable cases of this ticket handed to you – open the case to review the evidence" },
  { key: "all", label: "All", hint: "Every GP forwarded to you" },
];

const DAY_MS = 86_400_000;

export function SmeReviewTable({
  t,
  roles,
  picked,
  setPicked,
  onChanged,
  ndCases = [],
}: {
  t: TicketDetail;
  ndCases?: NdCaseRow[];
  roles: GpReviewRole[];
  picked: Set<number>;
  setPicked: (next: Set<number>) => void;
  onChanged: (next: TicketDetail, notice: Notice) => void;
}) {
  const task = t.task!;
  const [tab, setTab] = useState<SmeTab | null>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [act, setAct] = useState<{ action: GpReviewAction; gps: TicketTaskGp[] } | null>(null);
  const [nowMs] = useState(() => Date.now()); // the waiting time is counted from the page load
  const canAct = roles.includes("SME") && t.status !== "CLOSED";
  const pickable = (g: TicketTaskGp) => canAct && (canStep(g, "SME_FORWARD") || canStep(g, "SME_RETURN"));
  const query = q.trim().toLowerCase();
  const found = task.gps.filter((g) => !query || `${g.gpCode} ${g.gpName} ${g.block ?? ""} ${g.feName ?? ""} ${g.frtCode ?? ""}`.toLowerCase().includes(query));
  const ndFound = ndCases.filter((c) => !query || `${c.gpCode} ${c.gpName ?? ""} ${c.block ?? ""} ${c.fe ?? ""} ${c.ref}`.toLowerCase().includes(query));
  const ndPending = ndCases.some((c) => ndPendingFor(c, "SME"));
  const count = (k: SmeTab) => (k === "nd" ? ndFound.length : k === "all" ? found.length + ndFound.length : found.filter((g) => tabOf(g) === k).length);
  const now: SmeTab =
    tab ?? (task.gps.some((g) => tabOf(g) === "pending") ? "pending" : task.gps.some((g) => tabOf(g) === "coh") ? "coh" : ndPending ? "nd" : "all");
  const rows = now === "nd" ? [] : found.filter((g) => now === "all" || tabOf(g) === now);
  const ndRows = now === "nd" || now === "all" ? ndFound : [];
  const canPick = rows.filter(pickable);
  const detail = task.gps.find((g) => g.id === open) ?? null;
  // since when the GP waits at its current step (last review step, else the AM's approval)
  const since = (g: TicketTaskGp) => {
    const at = [...(g.trail ?? [])].reverse().find((x) => x.at)?.at ?? g.amApproval?.at ?? null;
    return at ? Math.max(0, Math.floor((nowMs - new Date(at).getTime()) / DAY_MS)) : null;
  };
  // the COH's latest send-back (its reason is shown with a GP returned by the COH)
  const cohBack = (g: TicketTaskGp) => [...(g.trail ?? [])].reverse().find((x) => x.action === "COH_RETURN");
  const toggle = (id: number, on: boolean) => {
    const next = new Set(picked);
    if (on) next.add(id);
    else next.delete(id);
    setPicked(next);
  };

  if (!task.gps.length && !ndCases.length) {
    return <p className="px-5 py-8 text-center text-[0.8125rem] text-muted-foreground">No GP of this ticket has been approved and forwarded to you by the Area Manager yet.</p>;
  }
  return (
    <>
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-2.5 text-[0.78125rem]">
        <span className="font-medium text-muted-foreground">Show GPs</span>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search GP code, name, block, FE, FRT…" className="h-9 w-72 text-[0.8125rem]" aria-label="Search GPs" />
        <span className="text-muted-foreground">
          {found.length + ndFound.length} of {task.gps.length + ndCases.length} GPs
        </span>
      </div>
      <div role="tablist" aria-label="GPs by stage" className="flex flex-wrap items-end gap-1 border-b border-border px-5 pt-2">
        {TABS.map((tb) => (
          <button
            key={tb.key}
            type="button"
            role="tab"
            aria-selected={now === tb.key}
            title={tb.hint}
            onClick={() => {
              setTab(tb.key);
              setPicked(new Set());
            }}
            className={cn(
              "-mb-px inline-flex items-center gap-2 rounded-t-md border-b-2 px-3 py-2 text-[0.8125rem] font-semibold",
              now === tb.key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {tb.label}
            <span
              className={cn(
                "rounded-full px-1.5 text-[0.6875rem]",
                tb.key === "nd" && ndPending
                  ? "bg-critical-soft text-critical-text"
                  : (tb.key === "pending" || tb.key === "coh") && count(tb.key)
                    ? tb.key === "coh" ? "bg-critical-soft text-critical-text" : "bg-warning-soft text-warning-text"
                    : "bg-muted text-foreground",
              )}
            >
              {count(tb.key)}
            </span>
          </button>
        ))}
      </div>
      <div className="max-h-[35rem] overflow-auto">
        <table className="w-full min-w-[76rem] text-[0.8125rem]">
          <caption className="sr-only">GPs forwarded to you for SME review</caption>
          <thead className="sticky top-0 z-10">
            <tr className="border-b border-border bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
              <th scope="col" className="w-8 px-3 py-2">
                <input
                  type="checkbox"
                  aria-label="Select all GPs that can be reviewed"
                  disabled={canPick.length === 0}
                  checked={canPick.length > 0 && canPick.every((g) => picked.has(g.id))}
                  onChange={(e) => setPicked(e.target.checked ? new Set(canPick.map((g) => g.id)) : new Set())}
                  className="size-4 accent-[var(--primary)]"
                />
              </th>
              {["GP Code", "GP Name · Block", "FE / FRT", "Field report", "Field proof", "AM approval", "AM proof", "Waiting", "Action"].map((h) => (
                <th key={h} scope="col" className="px-2 py-2">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && ndRows.length === 0 && (
              <tr>
                <td colSpan={10} className="px-5 py-6 text-center text-muted-foreground">
                  {now === "pending" ? "Nothing waiting for your review." : "No GPs here."}
                </td>
              </tr>
            )}
            {rows.map((g) => {
              const fe = g.feSubmission;
              const am = g.amApproval;
              const k = tabOf(g);
              const days = k === "pending" || k === "coh" ? since(g) : null;
              const stage = REVIEW_STAGE[stageOf(g)];
              const stripe = k === "pending" ? "border-l-warning" : k === "coh" ? "border-l-critical" : k === "forwarded" ? "border-l-good" : "border-l-transparent";
              return (
                <tr key={g.id} className={cn("border-b border-border/70 align-top transition-colors last:border-0 hover:bg-muted/40", k === "coh" && "bg-critical-soft/20")}>
                  <td className={cn("border-l-4 px-3 py-2.5", stripe)}>
                    <input
                      type="checkbox"
                      aria-label={`Select ${g.gpCode} for review`}
                      disabled={!pickable(g)}
                      checked={picked.has(g.id)}
                      onChange={(e) => toggle(g.id, e.target.checked)}
                      className="size-4 accent-[var(--primary)] disabled:opacity-30"
                    />
                  </td>
                  <td className="px-2 py-2.5">
                    <button type="button" onClick={() => setOpen(g.id)} className="font-semibold text-primary hover:underline" title="Open the GP details (FE submission, AM approval, history)">
                      {g.gpCode}
                    </button>
                    <span className="mt-0.5 block">
                      <TypeTag g={g} />
                    </span>
                  </td>
                  <td className="w-[11rem] px-2 py-2.5">
                    <span className="block font-medium">{g.gpName}</span>
                    <span className="block text-[0.75rem] text-muted-foreground">{g.block ?? "—"}</span>
                  </td>
                  <td className="w-[9.5rem] px-2 py-2.5">
                    <span className={cn("block font-medium", !g.feName && "text-warning-text")}>{g.feName ?? "FE not mapped"}</span>
                    {g.frtCode && <span className="block whitespace-nowrap text-[0.71875rem] text-muted-foreground">FRT {g.frtCode}</span>}
                  </td>
                  <td className="w-[13rem] px-2 py-2">
                    {fe ? <GpCategoryBadge code={fe.category} /> : <span className="text-muted-foreground">Not recorded</span>}
                    {fe?.remark && (
                      <span className="mt-0.5 line-clamp-2 block" title={fe.remark}>
                        {fe.remark}
                      </span>
                    )}
                    {fe?.submittedBy && (
                      <span className="block text-[0.6875rem] text-muted-foreground">
                        by {fe.submittedByRole} {fe.submittedBy}
                        {fe.submittedAt ? ` · ${ticketDay(fe.submittedAt)}` : ""}
                      </span>
                    )}
                  </td>
                  <td className="w-[10rem] px-2 py-2">
                    {g.files.length ? <FrtProofChips saved={g.files} draft={[]} disabled onRemove={() => undefined} /> : <span className="text-[0.75rem] text-muted-foreground">No proof</span>}
                  </td>
                  <td className="w-[13rem] px-2 py-2">
                    {am ? (
                      <>
                        <span className="block font-medium">{am.by}</span>
                        {am.remark && (
                          <span className="line-clamp-2 block" title={am.remark}>
                            {am.remark}
                          </span>
                        )}
                        {am.at && <span className="block text-[0.6875rem] text-muted-foreground">{ticketDay(am.at)}</span>}
                      </>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                    {k === "coh" && cohBack(g) && (
                      <span className="mt-1 block text-[0.6875rem] font-medium text-critical-text" title={cohBack(g)?.remark ?? undefined}>
                        COH: {cohBack(g)?.remark ?? "returned"}
                      </span>
                    )}
                  </td>
                  <td className="w-[10rem] px-2 py-2">
                    {am?.files?.length ? <FrtProofChips saved={am.files} draft={[]} disabled onRemove={() => undefined} /> : <span className="text-[0.75rem] text-muted-foreground">—</span>}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5">
                    {days !== null ? (
                      <span className={cn("rounded-full px-2 py-0.5 text-[0.71875rem] font-semibold", days > 2 ? "bg-critical-soft text-critical-text" : "bg-muted text-foreground")} title="Days since it reached you">
                        {days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"}`}
                      </span>
                    ) : (
                      <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold", stage.cls)}>{stage.label}</span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <span className="flex flex-col items-start gap-1">
                      {canAct && canStep(g, "SME_FORWARD") && (
                        <button
                          type="button"
                          onClick={() => setAct({ action: "SME_FORWARD", gps: [g] })}
                          className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-good px-2 py-1 text-[0.71875rem] font-semibold text-white hover:bg-good/90"
                          title="SME review – confirm the category and forward to the COH"
                        >
                          <CheckCircle2 className="size-3.5" aria-hidden /> Forward → COH
                        </button>
                      )}
                      {canAct && canStep(g, "SME_RETURN") && (
                        <button
                          type="button"
                          onClick={() => setAct({ action: "SME_RETURN", gps: [g] })}
                          className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-critical/40 px-2 py-1 text-[0.71875rem] font-semibold text-critical-text hover:bg-critical-soft"
                          title="Send back to the Area Manager (issue found)"
                        >
                          <Undo2 className="size-3.5" aria-hidden /> Back to AM
                        </button>
                      )}
                      <button type="button" onClick={() => setOpen(g.id)} className="text-[0.71875rem] font-medium text-primary hover:underline">
                        Details
                      </button>
                    </span>
                  </td>
                </tr>
              );
            })}
            {ndRows.map((c) => (
              <NdGpRow key={`nd-${c.id}`} c={c} role="SME" nowMs={nowMs} statusSpan={4} actionFirst={false} />
            ))}
          </tbody>
        </table>
      </div>
      <ReviewDialog
        t={t}
        action={act?.action ?? null}
        gps={act?.gps ?? []}
        onClose={() => setAct(null)}
        onDone={(next, notice) => {
          setAct(null);
          setPicked(new Set());
          onChanged(next, notice);
        }}
      />
      <GpDetailDialog t={t} g={detail} roles={roles} onClose={() => setOpen(null)} onChanged={onChanged} />
    </>
  );
}
