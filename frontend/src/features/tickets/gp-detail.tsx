"use client";

import { Eye, Send, Undo2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import type { GpReviewAction, GpReviewRecord, GpReviewRole, TicketDetail, TicketTask, TicketTaskGp } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { CATEGORY, GpCategoryBadge } from "./gp-category";
import { ticketDay, ticketTime, type Notice } from "./ticket-parts";
import { ProofList } from "./ticket-proof";
import { REVIEW_STAGE, ReviewDialog, canStep, stageOf } from "./ticket-review";

const week = (task: TicketTask) => task.week.id.replace("W-", "Week ");
const ROLE: Record<string, string> = { FE: "FE", AM: "Area Manager", SME: "SME", COH: "COH", ADMIN: "Admin" };

function StageBadge({ g }: { g: TicketTaskGp }) {
  const s = REVIEW_STAGE[stageOf(g)];
  return (
    <span className="inline-flex flex-col gap-0.5">
      <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold leading-snug", s.cls)}>{s.label}</span>
      {s.hint && <span className="text-[0.6875rem] font-medium text-muted-foreground">{s.hint}</span>}
    </span>
  );
}

const Empty = ({ children }: { children: React.ReactNode }) => <span className="text-muted-foreground">{children}</span>;

/**
 * Reviewer view of a GP-wise task – SME: only the GPs the Area Manager approved and forwarded to this SME; COH: only
 * the GPs the SME reviewed and forwarded to this COH (the backend sends nothing else). The FE's original Rectification
 * Done submission, the AM's verification (and for the COH the SME's review) side by side. Selection works with the
 * Review bar above the table (one or more GPs); the button opens the GP detail.
 */
export function SmeGpTable({
  t,
  kind = "SME",
  roles,
  picked,
  setPicked,
  onChanged,
}: {
  t: TicketDetail;
  kind?: "SME" | "COH";
  roles: GpReviewRole[];
  picked: Set<number>;
  setPicked: (next: Set<number>) => void;
  onChanged: (next: TicketDetail, notice: Notice) => void;
}) {
  const task = t.task!;
  const [open, setOpen] = useState<number | null>(null);
  const coh = kind === "COH";
  const pickable = (g: TicketTaskGp) =>
    t.status !== "CLOSED" &&
    (coh
      ? roles.includes("COH") && (canStep(g, "COH_LETTER") || canStep(g, "COH_AMC") || canStep(g, "COH_RETURN"))
      : roles.includes("SME") && (canStep(g, "SME_FORWARD") || canStep(g, "SME_RETURN")));
  const canPick = task.gps.filter(pickable);
  const detail = task.gps.find((g) => g.id === open) ?? null;
  const toggle = (id: number, on: boolean) => {
    const next = new Set(picked);
    if (on) next.add(id);
    else next.delete(id);
    setPicked(next);
  };
  if (!task.gps.length) {
    return (
      <p className="px-5 py-8 text-center text-[0.8125rem] text-muted-foreground">
        {coh ? "No GP of this ticket has been reviewed and forwarded to you by the SME yet." : "No GP of this ticket has been approved and forwarded to you by the Area Manager yet."}
      </p>
    );
  }
  const headers = [
    "Ticket ID", "GP Code", "GP Name", "Circle", "Block", "Target Week", "FE Name", "Original FE Category", "Original FE Remarks", "Supporting Evidence", "AM Verification Remarks", "AM Approval Date",
    ...(coh ? ["SME Review Remarks", "SME Review Date"] : []), "Workflow Status", "Action",
  ];
  return (
    <>
      <div className="max-h-[35rem] overflow-auto">
        <table className="w-full min-w-[110rem] text-[0.8125rem]">
          <caption className="sr-only">GPs forwarded to you for SME review</caption>
          <thead className="sticky top-0 z-10">
            <tr className="border-b border-border bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
              <th scope="col" className="w-8 px-3 py-2">
                <input
                  type="checkbox"
                  aria-label="Select all GPs pending your review"
                  disabled={canPick.length === 0}
                  checked={canPick.length > 0 && canPick.every((g) => picked.has(g.id))}
                  onChange={(e) => setPicked(e.target.checked ? new Set(canPick.map((g) => g.id)) : new Set())}
                  className="size-4 accent-[var(--primary)]"
                />
              </th>
              {headers.map((h) => (
                <th key={h} scope="col" className={cn("px-3 py-2", h === "Action" && "text-center")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {task.gps.map((g) => {
              const fe = g.feSubmission;
              const am = g.amApproval;
              return (
                <tr key={g.id} className="border-b border-border/70 align-top last:border-0">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`Select ${g.gpCode} for review`}
                      disabled={!pickable(g)}
                      checked={picked.has(g.id)}
                      onChange={(e) => toggle(g.id, e.target.checked)}
                      className="size-4 accent-[var(--primary)] disabled:opacity-30"
                    />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{t.code}</td>
                  <td className="px-3 py-2">
                    <button type="button" onClick={() => setOpen(g.id)} className="font-semibold text-primary hover:underline">
                      {g.gpCode}
                    </button>
                  </td>
                  <td className="min-w-[10rem] px-3 py-2">{g.gpName}</td>
                  <td className="px-3 py-2">{g.circle}</td>
                  <td className="min-w-[8rem] px-3 py-2 text-muted-foreground">{g.block ?? "—"}</td>
                  <td className="whitespace-nowrap px-3 py-2">{week(task)}</td>
                  <td className="px-3 py-2">{g.feName ?? <Empty>Not mapped</Empty>}</td>
                  <td className="px-3 py-2">{fe ? <GpCategoryBadge code={fe.category} /> : <Empty>Not recorded</Empty>}</td>
                  <td className="min-w-[12rem] max-w-[16rem] px-3 py-2">{fe?.remark ?? <Empty>No remark</Empty>}</td>
                  <td className="min-w-[11rem] max-w-[15rem] px-3 py-2">
                    <ProofList files={g.files} compact />
                  </td>
                  <td className="min-w-[12rem] max-w-[16rem] px-3 py-2">{am?.remark ?? <Empty>—</Empty>}</td>
                  <td className="whitespace-nowrap px-3 py-2">{am?.at ? ticketTime(am.at) : <Empty>—</Empty>}</td>
                  {coh && (
                    <>
                      <td className="min-w-[12rem] max-w-[16rem] px-3 py-2">{g.smeReview?.remark ?? <Empty>—</Empty>}</td>
                      <td className="whitespace-nowrap px-3 py-2">{g.smeReview?.at ? ticketTime(g.smeReview.at) : <Empty>—</Empty>}</td>
                    </>
                  )}
                  <td className="w-[13rem] px-3 py-2">
                    <StageBadge g={g} />
                  </td>
                  <td className="px-3 py-2 text-center">
                    <Button size="sm" variant={pickable(g) && !coh ? "primary" : "outline"} onClick={() => setOpen(g.id)} title={pickable(g) && !coh ? "Open and review this GP" : "Open the GP details"}>
                      {pickable(g) && !coh ? <Send /> : <Eye />} {pickable(g) && !coh ? "Review" : "View"}
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <GpDetailDialog t={t} g={detail} roles={roles} onClose={() => setOpen(null)} onChanged={onChanged} />
    </>
  );
}

function Section({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border">
      <h3 className="border-b border-border bg-muted/50 px-3 py-1.5 text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">
        {n}. {title}
      </h3>
      <div className="px-3 py-2.5 text-[0.8125rem]">{children}</div>
    </section>
  );
}

function Fields({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 sm:grid-cols-[11rem_1fr]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="font-medium text-muted-foreground">{k}</dt>
          <dd className="min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

const people = (r: GpReviewRecord) =>
  r.forwardedTo.length ? r.forwardedTo.map((p) => `${p.name} <${p.email}>`).join(", ") : <Empty>Not recorded (approved before GP-level forwarding)</Empty>;

/**
 * One GP in separate sections: GP information, the FE's original submission, the supporting evidence, the AM's
 * verification and approval, the current workflow status (with the SME review once done) and the review history.
 * The SME reviews this GP alone from here (Review & Forward → COH).
 */
export function GpDetailDialog({
  t,
  g,
  roles,
  onClose,
  onChanged,
}: {
  t: TicketDetail;
  g: TicketTaskGp | null;
  roles: GpReviewRole[];
  onClose: () => void;
  onChanged: (next: TicketDetail, notice: Notice) => void;
}) {
  const [reviewing, setReviewing] = useState<GpReviewAction | null>(null);
  const task = t.task!;
  // the steps this user can take on this GP from here (SME: forward / back to AM · COH: back to SME; letter / AMC in the bar)
  const actions = (["SME_FORWARD", "SME_RETURN", "COH_RETURN"] as GpReviewAction[]).filter(
    (a) => !!g && t.status !== "CLOSED" && roles.includes(a.startsWith("SME") ? "SME" : "COH") && canStep(g, a),
  );
  return (
    <>
      <Dialog open={g !== null && reviewing === null} onOpenChange={(o) => !o && onClose()}>
        <DialogContent className="max-h-[88vh] max-w-3xl overflow-y-auto">
          {g && (
            <div className="space-y-3 p-5">
              <div>
                <DialogTitle className="text-lg font-bold">
                  GP {g.gpCode} – {g.gpName}
                </DialogTitle>
                <DialogDescription className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                  {t.code} · {week(task)} · <StageBadge g={g} />
                </DialogDescription>
              </div>

              <Section n={1} title="GP Information">
                <Fields
                  rows={[
                    ["Ticket ID", t.code],
                    ["GP Code / Name", `${g.gpCode} – ${g.gpName}`],
                    ["Circle", g.circle],
                    ["District / Block", `${g.district ?? "—"} / ${g.block ?? "—"}`],
                    ["Target Week", `${week(task)} (${ticketDay(task.week.start)} – ${ticketDay(task.week.end)})`],
                    ["Area Manager", task.areaManager],
                    ["FE Name", g.feName ?? <Empty>Not mapped in the Escalation Matrix</Empty>],
                  ]}
                />
              </Section>

              <Section n={2} title="FE Original Submission">
                {g.feSubmission ? (
                  <Fields
                    rows={[
                      ["FE Name", g.feSubmission.feName ?? <Empty>Not mapped</Empty>],
                      ["Submitted by", `${g.feSubmission.submittedBy ?? "—"} (${ROLE[g.feSubmission.submittedByRole]})`],
                      ["Original FE Category", <GpCategoryBadge key="c" code={g.feSubmission.category} />],
                      ["Original FE Remarks", g.feSubmission.remark ?? <Empty>No remark</Empty>],
                      ["FE Submission Date", g.feSubmission.submittedAt ? ticketTime(g.feSubmission.submittedAt) : "—"],
                    ]}
                  />
                ) : (
                  <Empty>No Rectification Done submission is recorded for this GP.</Empty>
                )}
              </Section>

              <Section n={3} title="Existing Supporting Evidence">
                <ProofList files={g.files} emptyText="No supporting document uploaded" />
              </Section>

              <Section n={4} title="AM Verification and Approval">
                {g.amApproval ? (
                  <Fields
                    rows={[
                      ["AM Name", `${g.amApproval.by} (${ROLE[g.amApproval.role]})`],
                      ["AM Verification Remarks", g.amApproval.remark ?? <Empty>—</Empty>],
                      ["AM Approval Status", "Approved – Ready for Letter Submission"],
                      ["AM Approval Date and Time", g.amApproval.at ? ticketTime(g.amApproval.at) : "—"],
                      ["Current GP Category", <GpCategoryBadge key="c" code={g.gpCategory} />],
                      ["Forwarded to SME", people(g.amApproval)],
                      ["Forwarding Date and Time", g.amApproval.forwardedAt ? ticketTime(g.amApproval.forwardedAt) : <Empty>—</Empty>],
                    ]}
                  />
                ) : (
                  <Empty>Not approved by the Area Manager yet.</Empty>
                )}
              </Section>

              <Section n={5} title="Current Workflow Status">
                <div className="space-y-2">
                  <StageBadge g={g} />
                  {g.sentBack && (
                    <div className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2">
                      <Fields
                        rows={[
                          ["Sent back", g.sentBack.action === "SME_RETURN" ? "SME → Area Manager" : "COH → SME"],
                          ["By", `${g.sentBack.by} (${ROLE[g.sentBack.role]})`],
                          ["Reason", g.sentBack.remark ?? "—"],
                          ["Date and Time", g.sentBack.at ? ticketTime(g.sentBack.at) : "—"],
                        ]}
                      />
                    </div>
                  )}
                  {g.smeReview && (
                    <Fields
                      rows={[
                        ["SME Reviewer", `${g.smeReview.by} (${ROLE[g.smeReview.role]})`],
                        ["SME Review Remarks", g.smeReview.remark ?? <Empty>—</Empty>],
                        ["Confirmed Category", g.smeReview.category ? CATEGORY[g.smeReview.category].label : "—"],
                        ["Review Date and Time", g.smeReview.at ? ticketTime(g.smeReview.at) : "—"],
                        ["Forwarded to COH", people(g.smeReview)],
                      ]}
                    />
                  )}
                  {g.letterDate && <p>Letter submitted on {ticketDay(g.letterDate)}</p>}
                  {g.amcOn && <p>AMC converted on {ticketDay(g.amcOn)}</p>}
                </div>
              </Section>

              <Section n={6} title="Review History">
                {(g.trail ?? []).length ? (
                  <ol className="space-y-1.5 border-l border-border pl-3">
                    {(g.trail ?? []).map((x, i) => (
                      <li key={i}>
                        <span className="font-semibold">{x.label}</span> · {ROLE[x.role] ?? x.role} {x.by ?? ""}
                        {x.at && <span className="text-muted-foreground"> · {ticketTime(x.at)}</span>}
                        {x.fromStatus && x.toStatus && (
                          <span className="block text-[0.75rem] text-muted-foreground">
                            {x.fromStatus} → <b className="font-semibold text-foreground">{x.toStatus}</b>
                          </span>
                        )}
                        {x.remark && <span className="block text-[0.75rem] text-muted-foreground">“{x.remark}”</span>}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty>No review step yet.</Empty>
                )}
              </Section>

              <div className="flex justify-end gap-2 pt-1">
                <Button variant="outline" onClick={onClose}>
                  Close
                </Button>
                {actions.includes("SME_RETURN") && (
                  <Button variant="outline" onClick={() => setReviewing("SME_RETURN")}>
                    <Undo2 /> Back to AM
                  </Button>
                )}
                {actions.includes("COH_RETURN") && (
                  <Button variant="outline" onClick={() => setReviewing("COH_RETURN")}>
                    <Undo2 /> Back to SME
                  </Button>
                )}
                {actions.includes("SME_FORWARD") && (
                  <Button variant="primary" onClick={() => setReviewing("SME_FORWARD")}>
                    <Send /> Review & Forward → COH
                  </Button>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
      <ReviewDialog
        t={t}
        action={g ? reviewing : null}
        gps={g ? [g] : []}
        onClose={() => setReviewing(null)}
        onDone={(next, notice) => {
          setReviewing(null);
          onClose();
          onChanged(next, notice);
        }}
      />
    </>
  );
}
