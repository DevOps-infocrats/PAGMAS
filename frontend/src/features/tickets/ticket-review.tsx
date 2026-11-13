"use client";

import { CheckCircle2, FileCheck2, Loader2, Plus, Send, Undo2, Workflow, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { Input } from "@/components/ui/primitives";
import { useSession } from "@/components/providers/session-provider";
import { useApiQuery } from "@/hooks/use-api-query";
import { ticketApi, type GpReviewAction, type GpReviewRole, type GpStage, type ReviewContacts, type TicketDetail, type TicketTaskGp } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { CATEGORY } from "./gp-category";
import { TEXTAREA, ticketDay, ticketTime, type Notice } from "./ticket-parts";
import { ProofList } from "./ticket-proof";

/**
 * Review chain of the GPs of a task ticket (backend: app/tickets/review.py), with the SOP status wording:
 * FE classifies (A / C / D) → Pending AM Verification → Area Manager approves (Ready for Letter Submission – AM
 * Approved, to the SME it chose) or returns (to the FE) → SME Reviewed – Forwarded to COH → COH records the letter
 * submission (E, achieved) and the AMC conversion. D "Non-Doable – Proposed" opens a Non-Doable case instead
 * (Non-Doable Cases page); a GP approved Non-Doable is closed and locked.
 */
export const REVIEW_STAGE: Record<GpStage, { label: string; cls: string; hint?: string }> = {
  NONE: { label: "With FE", cls: "bg-muted text-muted-foreground" },
  PENDING_AM: { label: "Pending AM Verification", cls: "bg-warning-soft text-warning-text" },
  RETURNED: { label: "Returned to FE", cls: "bg-critical-soft text-critical-text" },
  AM_APPROVED: { label: "Ready for Letter Submission – AM Approved", cls: "bg-primary-soft text-primary", hint: "Pending SME Review" },
  SME_RETURNED: { label: "Returned to AM by SME", cls: "bg-critical-soft text-critical-text", hint: "Pending AM re-verification" },
  SME_FORWARDED: { label: "SME Reviewed – Forwarded to COH", cls: "bg-[color-mix(in_srgb,var(--series-1)_14%,transparent)] text-[var(--series-1)]", hint: "Pending COH – letter submission" },
  COH_RETURNED: { label: "Returned to SME by COH", cls: "bg-critical-soft text-critical-text", hint: "Pending SME re-review" },
  LETTER_SUBMITTED: { label: "Letter Submitted", cls: "bg-[color-mix(in_srgb,var(--series-7)_14%,transparent)] text-[var(--series-7)]" },
  AMC_CONVERTED: { label: "AMC Converted", cls: "bg-good-soft text-good-text" },
  ND_APPROVED: { label: "Closed – Non-Doable", cls: "bg-critical-soft text-critical-text" },
};

/** Workflow stage of a GP (sent by the backend; derived the same way for older responses). */
export function stageOf(g: TicketTaskGp): GpStage {
  if (g.stage) return g.stage;
  if (g.review) return g.review;
  return g.gpCategory === "A" && !g.ndCase?.open ? "PENDING_AM" : "NONE";
}

/** The stage a GP can be in for each step, and who does it. */
const STEPS: Record<GpReviewAction, { role: GpReviewRole; label: string; title: string; ok: (g: TicketTaskGp) => boolean; remark: boolean; date?: boolean; icon: typeof Send }> = {
  // the AM verifies the FE's Rectification Done – or again, a GP the SME sent back (same rules as the backend)
  AM_APPROVE: {
    role: "AM", label: "Approve → SME", title: "Approve GP readiness and send to the SME", remark: true, icon: CheckCircle2,
    ok: (g) => (!g.review || g.review === "SME_RETURNED") && g.gpCategory === "A" && !g.ndCase?.open,
  },
  // the AM sends back what the FE reported: Rectification Done (correction) or Revisit Required (recheck) – not an
  // untouched GP, not Non-Doable (own case), not a GP in the FRT revisit of a rejected Non-Doable case
  AM_RETURN: {
    role: "AM", label: "Return to FE", title: "Return to the FE for correction / recheck", remark: true, icon: Undo2,
    ok: (g) =>
      (!g.review || g.review === "SME_RETURNED") && (g.gpCategory === "A" || g.gpCategory === "C") && !g.ndCase?.open &&
      !(g.gpCategory === "C" && g.ndCase?.status === "REJECTED" && g.ndCase.revisit !== "REVIEWED"),
  },
  SME_FORWARD: {
    role: "SME", label: "Review & Forward → COH", title: "SME review – confirm the category and forward to the COH", remark: true, icon: Send,
    ok: (g) => g.review === "AM_APPROVED" || g.review === "COH_RETURNED",
  },
  SME_RETURN: {
    role: "SME", label: "Back to AM", title: "Send back to the Area Manager (issue found) – the AM verifies it again", remark: true, icon: Undo2,
    ok: (g) => g.review === "AM_APPROVED" || g.review === "COH_RETURNED",
  },
  COH_LETTER: { role: "COH", label: "Letter submitted", title: "Record the letter submission", remark: false, date: true, icon: FileCheck2, ok: (g) => g.review === "SME_FORWARDED" && g.gpCategory === "B" },
  COH_AMC: { role: "COH", label: "AMC converted", title: "Record the AMC conversion", remark: false, date: true, icon: Workflow, ok: (g) => g.review === "LETTER_SUBMITTED" },
  COH_RETURN: { role: "COH", label: "Back to SME", title: "Send back to the SME (issue found) – the SME reviews it again", remark: true, icon: Undo2, ok: (g) => g.review === "SME_FORWARDED" },
};
/** The send-back steps (outline buttons; the reason is mandatory). */
const BACK: GpReviewAction[] = ["AM_RETURN", "SME_RETURN", "COH_RETURN"];
const ROLE_NAME: Record<string, string> = { FE: "FE", AM: "AM", SME: "SME", COH: "COH", ADMIN: "Admin" };

/** Whether this GP can take any step of the given roles now (for the selection checkbox). */
export const reviewable = (g: TicketTaskGp, roles: GpReviewRole[]) => (Object.values(STEPS) as (typeof STEPS)[GpReviewAction][]).some((s) => roles.includes(s.role) && s.ok(g));

/** Stage badge, the latest review remark and the GP's full history (edits, additions, review steps). */
export function ReviewCell({ g }: { g: TicketTaskGp }) {
  const stage = REVIEW_STAGE[stageOf(g)];
  const trail = g.trail ?? [];
  const last = [...trail].reverse().find((x) => x.action !== "EDIT" && x.action !== "ADD");
  const role = last ? (ROLE_NAME[last.role] ?? last.role) : "";
  const lastText = last
    ? [role, last.by, last.at && ticketDay(last.at), last.date && ticketDay(last.date)].filter(Boolean).join(" · ") + (last.remark ? ` – “${last.remark}”` : "")
    : "";
  return (
    <div className="w-[13.75rem] space-y-0.5">
      <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
        <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold leading-snug", stage.cls)}>{stage.label}</span>
        {stage.hint && <span className="text-[0.6875rem] font-medium text-muted-foreground">{stage.hint}</span>}
        {g.ndCase && (
          <Link href={`/dashboard/tickets/non-doable?case=${g.ndCase.id}`} className="text-[0.71875rem] font-medium text-primary hover:underline" title={`Open the Non-Doable case – ${g.ndCase.label}`}>
            {g.ndCase.ref}
          </Link>
        )}
      </div>
      {last && (
        <p className="truncate text-[0.71875rem] leading-snug text-muted-foreground" title={lastText}>
          <b className="font-semibold text-foreground">{role}</b>
          {lastText.slice(role.length)}
        </p>
      )}
      {trail.length > 0 && (
        <details className="text-[0.71875rem]">
          <summary className="cursor-pointer font-medium text-primary">History ({trail.length})</summary>
          <ol className="mt-1 space-y-1 border-l border-border pl-2">
            {trail.map((x, i) => (
              <li key={i}>
                <span className="font-semibold">{x.label}</span> · {ROLE_NAME[x.role]} {x.by ?? ""}
                {x.at && <span className="text-muted-foreground"> · {ticketTime(x.at)}</span>}
                {x.category && <span> · {CATEGORY[x.category]?.label}</span>}
                {x.date && <span> · {ticketDay(x.date)}</span>}
                {x.fromStatus && x.toStatus && (
                  <span className="block text-muted-foreground">
                    {x.fromStatus} → <b className="font-semibold text-foreground">{x.toStatus}</b>
                  </span>
                )}
                {x.remark && <span className="block text-muted-foreground">{x.remark}</span>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}

/** Review actions of the signed-in user for the selected GPs (AM / SME / COH; an admin sees every step). */
export function ReviewBar({
  t,
  roles,
  selected,
  onClear,
  onChanged,
}: {
  t: TicketDetail;
  roles: GpReviewRole[];
  selected: TicketTaskGp[];
  onClear: () => void;
  onChanged: (next: TicketDetail, notice: Notice) => void;
}) {
  const [action, setAction] = useState<GpReviewAction | null>(null);
  const steps = (Object.keys(STEPS) as GpReviewAction[]).filter((a) => roles.includes(STEPS[a].role));
  const who = roles.length === 3 ? "Admin" : roles.map((r) => (r === "AM" ? "Area Manager" : r)).join(" / ");
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted/40 px-5 py-2.5 text-[0.78125rem]">
      <span className="font-semibold text-subheading">Review ({who})</span>
      <span className="text-muted-foreground">{selected.length ? `${selected.length} GP${selected.length === 1 ? "" : "s"} selected` : "Select GPs in the table"}</span>
      {steps.map((a) => {
        const s = STEPS[a];
        const n = selected.filter(s.ok).length;
        const Icon = s.icon;
        const revisit = a === "AM_APPROVE" ? selected.filter((g) => g.gpCategory === "C").length : 0;
        const why = revisit
          ? `${revisit} selected GP${revisit === 1 ? " is" : "s are"} Revisit Required – these can only be returned to the FE (Approve is for Rectification Done)`
          : `${selected.length - n} selected GP(s) are not at this stage`;
        return (
          <Button key={a} size="sm" variant={BACK.includes(a) ? "outline" : "primary"} disabled={!selected.length || n !== selected.length} onClick={() => setAction(a)} title={n !== selected.length && selected.length ? why : s.title}>
            <Icon /> {s.label}
          </Button>
        );
      })}
      {selected.length > 0 && (
        <button type="button" onClick={onClear} className="rounded px-1.5 py-0.5 text-[0.75rem] font-medium text-primary hover:bg-primary-soft">
          Clear selection
        </button>
      )}
      <ReviewDialog
        t={t}
        action={action}
        gps={selected}
        onClose={() => setAction(null)}
        onDone={(next, notice) => {
          setAction(null);
          onClear();
          onChanged(next, notice);
        }}
      />
    </div>
  );
}

/** Whether this GP can take the given step now (same rule as the backend's state check). */
export const canStep = (g: TicketTaskGp, action: GpReviewAction) => STEPS[action].ok(g);

/** The form of one review step for the given GPs, in a dialog (`action` null = closed). */
export function ReviewDialog({
  t,
  action,
  gps,
  onClose,
  onDone,
}: {
  t: TicketDetail;
  action: GpReviewAction | null;
  gps: TicketTaskGp[];
  onClose: () => void;
  onDone: (next: TicketDetail, notice: Notice) => void;
}) {
  return (
    <Dialog open={action !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">{action && <ReviewForm t={t} action={action} gps={gps} onCancel={onClose} onDone={onDone} />}</DialogContent>
    </Dialog>
  );
}

export const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export type Typed = { key: number; name: string; email: string };

/** Who receives the GPs of the step (SME for the approval, COH for the forward): the circle's people from the
 * Escalation Matrix (pre-selected), or a name / e-mail typed by the user. */
export function SendTo({ role, contacts: c, loading, failed, picked, setPicked, typed, setTyped, disabled }: {
  role: "SME" | "COH";
  contacts: ReviewContacts | undefined;
  loading: boolean;
  failed: boolean;
  picked: Record<string, string>;
  setPicked: (v: Record<string, string>) => void;
  typed: Typed[];
  setTyped: (v: Typed[]) => void;
  disabled: boolean;
}) {
  const toggle = (email: string, name: string, on: boolean) => {
    const next = { ...picked };
    if (on) next[email] = name;
    else delete next[email];
    setPicked(next);
  };
  const people = [...(c?.people ?? []), ...(c?.onTicket ?? []).map((r) => ({ name: r.name, emails: [{ email: r.email, account: r.account, onTicket: true }] }))];
  return (
    <fieldset className="space-y-2 rounded-lg border border-border p-3">
      <legend className="px-1 text-[0.8125rem] font-medium">
        Send to {role} {c?.circle ? <span className="font-normal text-muted-foreground">– {c.circle}, from the Escalation Matrix</span> : null}
      </legend>
      {loading && !c ? (
        <p className="flex items-center gap-2 text-[0.78125rem] text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" /> Loading the {role}…
        </p>
      ) : failed ? (
        <p className="text-[0.78125rem] text-critical-text">Could not load the {role} list – type the e-mail below.</p>
      ) : people.length === 0 ? (
        <p className="text-[0.78125rem] text-warning-text">No {role} of this circle in the Escalation Matrix – type the name and e-mail below.</p>
      ) : (
        <ul className="space-y-1.5">
          {people.map((p) =>
            p.emails.map((e) => (
              <li key={e.email}>
                <label className="flex cursor-pointer items-start gap-2 text-[0.8125rem]">
                  <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" disabled={disabled} checked={e.email in picked} onChange={(ev) => toggle(e.email, p.name, ev.target.checked)} />
                  <span>
                    <b className="font-semibold">{p.name}</b> <span className="text-muted-foreground">· {e.email}</span>
                    <span className={cn("ml-1.5 rounded px-1.5 py-0.5 text-[0.65625rem] font-semibold", e.account ? "bg-good-soft text-good-text" : "bg-muted text-muted-foreground")}>
                      {e.account ? "dashboard account" : "e-mail only"}
                    </span>
                    {e.onTicket && <span className="ml-1 rounded bg-primary-soft px-1.5 py-0.5 text-[0.65625rem] font-semibold text-primary">on this ticket</span>}
                  </span>
                </label>
              </li>
            )),
          )}
        </ul>
      )}
      {typed.map((r) => {
        const upd = (patch: Partial<Typed>) => setTyped(typed.map((x) => (x.key === r.key ? { ...x, ...patch } : x)));
        const bad = r.email.trim() !== "" && !EMAIL.test(r.email.trim());
        return (
          <div key={r.key} className="flex gap-2">
            <Input value={r.name} onChange={(e) => upd({ name: e.target.value })} maxLength={160} placeholder={`${role} name`} disabled={disabled} className="h-8 flex-1 text-[0.8125rem]" aria-label={`${role} name`} />
            <Input value={r.email} onChange={(e) => upd({ email: e.target.value })} maxLength={254} type="email" placeholder="name@example.com" disabled={disabled} aria-invalid={bad} className={cn("h-8 flex-[1.4] text-[0.8125rem]", bad && "border-critical")} aria-label={`${role} e-mail`} />
            <button type="button" disabled={disabled} onClick={() => setTyped(typed.filter((x) => x.key !== r.key))} className="rounded p-1 text-muted-foreground hover:bg-accent" aria-label="Remove this e-mail">
              <X className="size-3.5" />
            </button>
          </div>
        );
      })}
      <button
        type="button"
        disabled={disabled || typed.length >= 5}
        onClick={() => setTyped([...typed, { key: Date.now(), name: "", email: "" }])}
        className="inline-flex items-center gap-1 rounded px-1 py-0.5 text-[0.78125rem] font-medium text-primary hover:bg-primary-soft disabled:opacity-50"
      >
        <Plus className="size-3.5" /> Add another e-mail
      </button>
    </fieldset>
  );
}

function ReviewForm({ t, action, gps, onCancel, onDone }: { t: TicketDetail; action: GpReviewAction; gps: TicketTaskGp[]; onCancel: () => void; onDone: (next: TicketDetail, notice: Notice) => void }) {
  const s = STEPS[action];
  const today = new Date().toLocaleDateString("en-CA");
  const [remark, setRemark] = useState("");
  const { session } = useSession();
  const sme = action === "SME_FORWARD";
  // SME: the confirmed category is an explicit choice (only B in the normal readiness workflow – Non-Doable has its own cases)
  const [confirmed, setConfirmed] = useState<"B" | "">("");
  const reviewerRole = (t.can.reviewAs?.length ?? 0) === 3 ? "Admin (acting as SME)" : "SME"; // admins may do every step

  const [date, setDate] = useState(today);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toRole = action === "AM_APPROVE" ? "SME" : action === "SME_FORWARD" ? "COH" : null;
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [typed, setTyped] = useState<Typed[]>([]);
  const q = useApiQuery(toRole ? `review-contacts:${t.id}:${toRole}` : null, () => ticketApi.getReviewContacts(t.id, toRole ?? "SME"));
  const [seeded, setSeeded] = useState<ReviewContacts | null>(null);
  if (q.data && seeded !== q.data) {
    // pre-select: who is already on the ticket, else every matrix person's first e-mail
    const c = q.data;
    const on: Record<string, string> = {};
    for (const p of c.people) for (const e of p.emails) if (e.onTicket) on[e.email] = p.name;
    for (const r of c.onTicket) on[r.email] = r.name;
    if (!Object.keys(on).length) for (const p of c.people) if (p.emails[0]) on[p.emails[0].email] = p.name;
    setSeeded(c);
    setPicked(on);
    if (!c.people.length && !c.onTicket.length) setTyped([{ key: 1, name: "", email: "" }]);
  }
  const typedOk = typed.filter((r) => EMAIL.test(r.email.trim()));
  const typedBad = typed.some((r) => r.email.trim() !== "" && !EMAIL.test(r.email.trim()));
  const to = toRole ? [...Object.entries(picked).map(([email, name]) => ({ name, email })), ...typedOk.map((r) => ({ name: r.name.trim() || undefined, email: r.email.trim() }))] : [];
  const noTo = toRole !== null && to.length === 0;
  const tooShort = s.remark && remark.trim().length < 3;
  const noCategory = sme && confirmed === "";
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      const next = await ticketApi.reviewGps(t.id, {
        taskGpIds: gps.map((g) => g.id),
        action,
        remark: remark.trim() || undefined,
        ...(sme && confirmed ? { category: confirmed } : {}),
        ...(s.date ? { date } : {}),
        ...(toRole ? { to } : {}),
      });
      const whom = toRole ? ` E-mail sent to ${to.map((x) => x.email).join(", ")}.` : "";
      onDone(next, { ok: true, text: `${s.title}: ${gps.length} GP${gps.length === 1 ? "" : "s"} done. Everyone concerned has been notified.${whom}` });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the review step");
      setBusy(false);
    }
  };
  return (
    <form
      className="space-y-4 p-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!tooShort && !noCategory && !busy) void send();
      }}
    >
      <div>
        <DialogTitle className="text-lg font-bold">{s.title}</DialogTitle>
        <DialogDescription className="mt-1 text-sm text-muted-foreground">
          {gps.length} GP{gps.length === 1 ? "" : "s"}: {gps.slice(0, 8).map((g) => g.gpCode).join(", ")}
          {gps.length > 8 ? ` … (+${gps.length - 8})` : ""}
          {action === "AM_APPROVE" && " – Rectification Done becomes Ready for Letter Submission – AM Approved and goes only to the SME you choose; the GP can no longer be changed by the FE."}
          {action === "AM_RETURN" &&
            (gps.every((g) => g.gpCategory === "C")
              ? " – Revisit Required: the FE is asked to recheck with the FRT team and update the GP again."
              : " – the FE corrects the GP and submits it again; it then comes back to you.")}
          {sme && " – the GP becomes SME Reviewed – Forwarded to COH."}
          {action === "SME_RETURN" && " – the GP goes back to the Area Manager (Returned to AM by SME): the AM verifies it again and approves it or returns it to the FE."}
          {action === "COH_RETURN" && " – the GP goes back to the SME (Returned to SME by COH): the SME reviews it again and forwards it or sends it back to the AM."}
          {action === "COH_LETTER" && " – the GP becomes Letter Submission Done (counted as achieved)."}
        </DialogDescription>
      </div>
      {action === "AM_APPROVE" && (
        <fieldset className="space-y-2 rounded-lg border border-border p-3">
          <legend className="px-1 text-[0.8125rem] font-medium">Proof uploaded for these GPs</legend>
          <ul className="max-h-60 space-y-2 overflow-y-auto">
            {gps.map((g) => (
              <li key={g.id} className="space-y-1">
                <p className="text-[0.78125rem]">
                  <b className="font-semibold">{g.gpCode}</b> {g.gpName}
                </p>
                <ProofList files={g.files} compact emptyText="No proof uploaded" />
              </li>
            ))}
          </ul>
        </fieldset>
      )}
      {sme && (
        <fieldset className="space-y-1.5 rounded-lg border border-border p-3">
          <legend className="px-1 text-[0.8125rem] font-medium">
            Confirmed Category <span className="text-critical-text">*</span>
          </legend>
          <label className="flex cursor-pointer items-center gap-2 text-[0.8125rem]">
            <input type="radio" name="confirmed-category" className="size-4 accent-[var(--primary)]" checked={confirmed === "B"} onChange={() => setConfirmed("B")} disabled={busy} />
            <b className="font-semibold">{CATEGORY.B.label}</b>
          </label>
          <p className="text-[0.75rem] text-muted-foreground">A Non-Doable GP is not confirmed here – it goes through its own Non-Doable case.</p>
        </fieldset>
      )}
      {s.date && (
        <label className="block space-y-1">
          <span className="text-[0.8125rem] font-medium">{action === "COH_LETTER" ? "Letter submission date" : "AMC conversion date"}</span>
          <Input type="date" value={date} max={today} onChange={(e) => setDate(e.target.value)} required className="h-9" />
        </label>
      )}
      {toRole && (
        <SendTo role={toRole} contacts={q.data} loading={q.loading} failed={!!q.error} picked={picked} setPicked={setPicked} typed={typed} setTyped={setTyped} disabled={busy} />
      )}
      <label className="block space-y-1">
        <span className="text-[0.8125rem] font-medium">
          {action === "AM_RETURN"
            ? "Reason – what the FE should correct / recheck"
            : action === "SME_RETURN"
              ? "Reason – what the Area Manager should check"
              : action === "COH_RETURN"
                ? "Reason – what the SME should check"
                : sme
                  ? "SME Review Remarks"
                  : action === "AM_APPROVE"
                    ? "AM Verification Remarks"
                    : s.remark
                      ? "Remark"
                      : "Remark (optional)"}
          {s.remark && <span className="text-critical-text"> *</span>}
        </span>
        <textarea
          value={remark}
          onChange={(e) => setRemark(e.target.value)}
          rows={3}
          maxLength={1000}
          className={TEXTAREA}
          placeholder={
            action === "AM_RETURN"
              ? "What the FE has to correct…"
              : action === "SME_RETURN" || action === "COH_RETURN"
                ? "The issue found…"
                : sme
                  ? "Your review of the FE submission and the AM verification…"
                  : "Verification / review remark…"
          }
        />
        {s.remark && tooShort && remark.length > 0 && <span className="text-[0.75rem] text-critical-text">At least 3 characters.</span>}
      </label>
      {sme && (
        <p className="rounded-md bg-muted/60 px-3 py-2 text-[0.75rem] text-muted-foreground">
          Recorded automatically: reviewer <b className="font-semibold text-foreground">{session?.name ?? "you"}</b> ({reviewerRole}) · review date and time = when you submit.
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="primary"
          disabled={busy || tooShort || noCategory || (s.date === true && !date) || noTo || typedBad}
          title={noCategory ? "Choose the confirmed category" : noTo ? `Choose or type the ${toRole} e-mail` : undefined}
        >
          {busy && <Loader2 className="animate-spin" />} {s.label}
        </Button>
      </div>
    </form>
  );
}
