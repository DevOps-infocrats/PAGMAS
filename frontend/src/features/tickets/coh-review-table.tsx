"use client";

/**
 * COH view of a GP-wise task (User Tickets, COH login only – the SME has SmeReviewTable): the GPs the SME reviewed and
 * forwarded to this COH, in work tabs (letter pending first), with the field report, the AM's approval, the SME's
 * review, the three proofs (FE / AM / SME), the waiting time or the letter / AMC dates and the row's step (Letter
 * submitted / AMC converted / Back to SME). The GP detail (all sections, history) opens from the GP code / Details.
 * Who may do which step stays in ticket-review.tsx (canStep) and the backend.
 */

import { BadgeCheck, FileCheck2, Undo2 } from "lucide-react";
import { useState } from "react";
import { Input } from "@/components/ui/primitives";
import type { GpReviewAction, GpReviewRole, NdCaseRow, TicketDetail, TicketProofFile, TicketTaskGp } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { TypeTag } from "./fe-task-parts";
import { FrtProofChips } from "./frt-task-parts";
import { GpCategoryBadge } from "./gp-category";
import { GpDetailDialog } from "./gp-detail";
import { NdGpRow, ndPendingFor } from "./nd-gp-rows";
import { ticketDay, type Notice } from "./ticket-parts";
import { REVIEW_STAGE, ReviewDialog, canStep, stageOf } from "./ticket-review";

type CohTab = "nd" | "letter" | "amc" | "done" | "back" | "all";

/** Which tab a GP is in (by its review state). */
const tabOf = (g: TicketTaskGp): Exclude<CohTab, "all"> | null =>
  g.review === "SME_FORWARDED" ? "letter" : g.review === "LETTER_SUBMITTED" ? "amc" : g.review === "AMC_CONVERTED" ? "done" : g.review === "COH_RETURNED" ? "back" : null;

const TABS: { key: CohTab; label: string; hint: string }[] = [
  { key: "letter", label: "Letter pending", hint: "Reviewed and forwarded by the SME – record the letter submission, or send back" },
  { key: "amc", label: "AMC pending", hint: "Letter submitted – record the AMC conversion" },
  { key: "done", label: "AMC converted", hint: "Letter submitted and AMC converted" },
  { key: "back", label: "Sent back to SME", hint: "Sent back by you – waiting for the SME" },
  { key: "nd", label: "Non-Doable", hint: "Non-Doable cases of this ticket handed to you – open the case to review the evidence" },
  { key: "all", label: "All", hint: "Every GP forwarded to you" },
];

const DAY_MS = 86_400_000;

/** One step's proof with its label (FE / AM / SME). */
function ProofGroup({ label, files }: { label: string; files: TicketProofFile[] | undefined }) {
  if (!files?.length) return null;
  return (
    <span className="flex items-center gap-1.5">
      <span className="shrink-0 text-[0.625rem] font-semibold uppercase text-muted-foreground">{label}</span>
      <FrtProofChips saved={files} draft={[]} disabled onRemove={() => undefined} />
    </span>
  );
}

/** Who did a review step, its remark and date, in one cell. */
function StepCell({ by, remark, at }: { by?: string | null; remark?: string | null; at?: string | null }) {
  if (!by && !remark) return <span className="text-muted-foreground">—</span>;
  return (
    <>
      {by && <span className="block font-medium">{by}</span>}
      {remark && (
        <span className="line-clamp-2 block" title={remark}>
          {remark}
        </span>
      )}
      {at && <span className="block text-[0.6875rem] text-muted-foreground">{ticketDay(at)}</span>}
    </>
  );
}

export function CohReviewTable({
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
  const [tab, setTab] = useState<CohTab | null>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [act, setAct] = useState<{ action: GpReviewAction; gps: TicketTaskGp[] } | null>(null);
  const [nowMs] = useState(() => Date.now()); // the waiting time is counted from the page load
  const canAct = roles.includes("COH") && t.status !== "CLOSED";
  const pickable = (g: TicketTaskGp) => canAct && (canStep(g, "COH_LETTER") || canStep(g, "COH_AMC") || canStep(g, "COH_RETURN"));
  const query = q.trim().toLowerCase();
  const found = task.gps.filter((g) => !query || `${g.gpCode} ${g.gpName} ${g.block ?? ""} ${g.feName ?? ""} ${g.frtCode ?? ""}`.toLowerCase().includes(query));
  const ndFound = ndCases.filter((c) => !query || `${c.gpCode} ${c.gpName ?? ""} ${c.block ?? ""} ${c.fe ?? ""} ${c.ref}`.toLowerCase().includes(query));
  const ndPending = ndCases.some((c) => ndPendingFor(c, "COH"));
  const count = (k: CohTab) => (k === "nd" ? ndFound.length : k === "all" ? found.length + ndFound.length : found.filter((g) => tabOf(g) === k).length);
  const first = (["letter", "amc"] as const).find((k) => task.gps.some((g) => tabOf(g) === k));
  const now: CohTab = tab ?? first ?? (ndPending ? "nd" : "all");
  const rows = now === "nd" ? [] : found.filter((g) => now === "all" || tabOf(g) === now);
  const ndRows = now === "nd" || now === "all" ? ndFound : [];
  const canPick = rows.filter(pickable);
  const detail = task.gps.find((g) => g.id === open) ?? null;
  // since when the GP waits at its current step (last review step, else the SME's review)
  const since = (g: TicketTaskGp) => {
    const at = [...(g.trail ?? [])].reverse().find((x) => x.at)?.at ?? g.smeReview?.at ?? null;
    return at ? Math.max(0, Math.floor((nowMs - new Date(at).getTime()) / DAY_MS)) : null;
  };
  const toggle = (id: number, on: boolean) => {
    const next = new Set(picked);
    if (on) next.add(id);
    else next.delete(id);
    setPicked(next);
  };

  if (!task.gps.length && !ndCases.length) {
    return <p className="px-5 py-8 text-center text-[0.8125rem] text-muted-foreground">No GP of this ticket has been reviewed and forwarded to you by the SME yet.</p>;
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
            <span className={cn("rounded-full px-1.5 text-[0.6875rem]", tb.key === "nd" && ndPending ? "bg-critical-soft text-critical-text" : (tb.key === "letter" || tb.key === "amc") && count(tb.key) ? "bg-warning-soft text-warning-text" : "bg-muted text-foreground")}>
              {count(tb.key)}
            </span>
          </button>
        ))}
      </div>
      <div className="max-h-[35rem] overflow-auto">
        <table className="w-full min-w-[74rem] text-[0.8125rem]">
          <caption className="sr-only">GPs forwarded to you by the SME</caption>
          <thead className="sticky top-0 z-10">
            <tr className="border-b border-border bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
              <th scope="col" className="w-8 px-3 py-2">
                <input
                  type="checkbox"
                  aria-label="Select all GPs you can act on"
                  disabled={canPick.length === 0}
                  checked={canPick.length > 0 && canPick.every((g) => picked.has(g.id))}
                  onChange={(e) => setPicked(e.target.checked ? new Set(canPick.map((g) => g.id)) : new Set())}
                  className="size-4 accent-[var(--primary)]"
                />
              </th>
              {["GP Code", "GP Name · Block", "FE / FRT", "Field report", "AM approval", "SME review", "Proof", "Action", "Waiting / Dates"].map((h) => (
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
                  {now === "letter" ? "No letter submission waiting." : now === "amc" ? "No AMC conversion waiting." : "No GPs here."}
                </td>
              </tr>
            )}
            {rows.map((g) => {
              const fe = g.feSubmission;
              const am = g.amApproval;
              const sme = g.smeReview;
              const k = tabOf(g);
              const days = k === "letter" || k === "amc" ? since(g) : null;
              const stage = REVIEW_STAGE[stageOf(g)];
              const stripe =
                k === "letter" ? "border-l-warning" : k === "amc" ? "border-l-[var(--series-1)]" : k === "done" ? "border-l-good" : k === "back" ? "border-l-critical" : "border-l-transparent";
              const proofs = !!(g.files.length || am?.files?.length || sme?.files?.length);
              return (
                <tr key={g.id} className="border-b border-border/70 align-top transition-colors last:border-0 hover:bg-muted/40">
                  <td className={cn("border-l-4 px-3 py-2.5", stripe)}>
                    <input
                      type="checkbox"
                      aria-label={`Select ${g.gpCode}`}
                      disabled={!pickable(g)}
                      checked={picked.has(g.id)}
                      onChange={(e) => toggle(g.id, e.target.checked)}
                      className="size-4 accent-[var(--primary)] disabled:opacity-30"
                    />
                  </td>
                  <td className="px-2 py-2.5">
                    <button type="button" onClick={() => setOpen(g.id)} className="font-semibold text-primary hover:underline" title="Open the GP details (FE submission, AM approval, SME review, history)">
                      {g.gpCode}
                    </button>
                    <span className="mt-0.5 block">
                      <TypeTag g={g} />
                    </span>
                  </td>
                  <td className="w-[9.5rem] px-2 py-2.5">
                    <span className="block font-medium">{g.gpName}</span>
                    <span className="block text-[0.75rem] text-muted-foreground">{g.block ?? "—"}</span>
                  </td>
                  <td className="w-[9rem] px-2 py-2.5">
                    <span className={cn("block font-medium", !g.feName && "text-warning-text")}>{g.feName ?? "FE not mapped"}</span>
                    {g.frtCode && <span className="block whitespace-nowrap text-[0.71875rem] text-muted-foreground">FRT {g.frtCode}</span>}
                  </td>
                  <td className="w-[11rem] px-2 py-2">
                    {fe ? <GpCategoryBadge code={fe.category} /> : <span className="text-muted-foreground">Not recorded</span>}
                    {fe?.remark && (
                      <span className="mt-0.5 line-clamp-2 block" title={fe.remark}>
                        {fe.remark}
                      </span>
                    )}
                    {fe?.submittedBy && (
                      <span className="block text-[0.6875rem] text-muted-foreground">
                        by {fe.submittedByRole} {fe.submittedBy}
                      </span>
                    )}
                  </td>
                  <td className="w-[11rem] px-2 py-2">
                    <StepCell by={am?.by} remark={am?.remark} at={am?.at} />
                  </td>
                  <td className="w-[11rem] px-2 py-2">
                    <StepCell by={sme?.by} remark={sme?.remark} at={sme?.at} />
                    {sme?.category && (
                      <span className="mt-0.5 block">
                        <GpCategoryBadge code={sme.category} />
                      </span>
                    )}
                  </td>
                  <td className="w-[12.5rem] px-2 py-2">
                    {proofs ? (
                      <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                        <ProofGroup label="FE" files={g.files} />
                        <ProofGroup label="AM" files={am?.files} />
                        <ProofGroup label="SME" files={sme?.files} />
                      </span>
                    ) : (
                      <span className="text-[0.75rem] text-muted-foreground">No proof</span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    <span className="flex flex-col items-start gap-1">
                      {canAct && canStep(g, "COH_LETTER") && (
                        <button
                          type="button"
                          onClick={() => setAct({ action: "COH_LETTER", gps: [g] })}
                          className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-primary px-2 py-1 text-[0.71875rem] font-semibold text-primary-foreground hover:bg-primary/90"
                          title="Record the letter submission"
                        >
                          <FileCheck2 className="size-3.5" aria-hidden /> Letter submitted
                        </button>
                      )}
                      {canAct && canStep(g, "COH_AMC") && (
                        <button
                          type="button"
                          onClick={() => setAct({ action: "COH_AMC", gps: [g] })}
                          className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-good px-2 py-1 text-[0.71875rem] font-semibold text-white hover:bg-good/90"
                          title="Record the AMC conversion"
                        >
                          <BadgeCheck className="size-3.5" aria-hidden /> AMC converted
                        </button>
                      )}
                      {canAct && canStep(g, "COH_RETURN") && (
                        <button
                          type="button"
                          onClick={() => setAct({ action: "COH_RETURN", gps: [g] })}
                          className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-critical/40 px-2 py-1 text-[0.71875rem] font-semibold text-critical-text hover:bg-critical-soft"
                          title="Send back to the SME (issue found)"
                        >
                          <Undo2 className="size-3.5" aria-hidden /> Back to SME
                        </button>
                      )}
                      <button type="button" onClick={() => setOpen(g.id)} className="text-[0.71875rem] font-medium text-primary hover:underline">
                        Details
                      </button>
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-2.5">
                    {days !== null && (
                      <span className={cn("rounded-full px-2 py-0.5 text-[0.71875rem] font-semibold", days > 2 ? "bg-critical-soft text-critical-text" : "bg-muted text-foreground")} title="Days since it reached this step">
                        {days === 0 ? "today" : `${days} day${days === 1 ? "" : "s"}`}
                      </span>
                    )}
                    {g.letterDate && <span className="mt-1 block text-[0.71875rem]">Letter: {ticketDay(g.letterDate)}</span>}
                    {g.amcOn && <span className="block text-[0.71875rem] text-good-text">AMC: {ticketDay(g.amcOn)}</span>}
                    {days === null && !g.letterDate && !g.amcOn && <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold", stage.cls)}>{stage.label}</span>}
                  </td>
                </tr>
              );
            })}
            {ndRows.map((c) => (
              <NdGpRow key={`nd-${c.id}`} c={c} role="COH" nowMs={nowMs} statusSpan={4} actionFirst={true} />
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
