"use client";

import { ChevronDown, Download, FileSpreadsheet, ListChecks, Loader2, Paperclip, Plus, Send, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { ticketApi, type GpCategory, type GpStage, type NewTaskGp, type TicketDetail, type TicketTask } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";
import { TEXTAREA, fileSize, ticketDay, ticketTime, type Notice } from "./ticket-parts";
import { CATEGORY, GP_CATEGORIES, GpCategoryBadge, GpCategorySelect } from "./gp-category";
import { GpDetailDialog, SmeGpTable } from "./gp-detail";
import { GpStatusBadge, PROOF_ACCEPT, ProofList } from "./ticket-proof";
import { REVIEW_STAGE, ReviewBar, ReviewCell, reviewable, stageOf } from "./ticket-review";

const dm = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "UTC" });
const MAX_GP_FILES = 5; // per GP and submission (backend: task.MAX_GP_FILES)
const MAX_FILE_MB = 20; // per file (backend: TICKET_FILE_MAX_MB)
const ALL_FES = "__all";
const NO_FE = "__none";

const ALL_STAGES = "__all";
const GP_CODE = /^[A-Za-z0-9][A-Za-z0-9/_.-]{0,39}$/; // backend: task.GP_CODE_RE

/** Unsubmitted change of a GP: Daily Achievement category (A / C / D, null = unchanged), remark, proof files to attach,
 * corrected GP Name / Block (undefined = unchanged). */
type Draft = Record<number, { category: GpCategory | null; remark: string; files: File[]; gpName?: string; block?: string }>;
/** A GP row added by the FE / Area Manager, sent with the next submission. */
type NewRow = { key: number; gpCode: string; gpName: string; block: string; category: "A" | "C" | "D" | null; remark: string };

/**
 * GP-wise weekly task of a ticket (backend: app/tickets/task.py). Admin and Area Manager see the same figures, with the
 * FE-wise split; a Field Engineer sees only the GPs mapped to them (the backend sends nothing else). The Area Manager /
 * FE chooses each GP's status in the Daily Achievement dropdown (Rectification Done / Revisit Required / Non-Doable –
 * Proposed; a later choice replaces the GP's category), corrects the GP Name / Block, writes remarks, attaches proof
 * documents per GP and adds GP rows ("Submit Daily Progress" – every submission is kept). The review chain (Area
 * Manager approve / return, SME forward, COH letter / AMC) works on the same table; an approved GP is locked for the
 * daily progress. Targets and GP codes never change here; only an admin closes the ticket.
 */
export function TaskPanel({ t, admin, onChanged }: { t: TicketDetail; admin: boolean; onChanged: (next: TicketDetail, notice: Notice) => void }) {
  const task = t.task!;
  const editable = t.can.progress;
  const [draft, setDraft] = useState<Draft>({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // FE view = only their GPs; SME view = only the GPs the Area Manager forwarded to this SME (both cut by the backend)
  const reviewer = task.scope && task.scope.kind !== "FE" ? task.scope.kind : null; // "SME" | "COH" view
  const kpis = task.scope && task.scope.kind !== "FE" ? task.scope.kpis : undefined;
  const smeView = reviewer !== null;
  const scoped = task.scope && task.scope.kind === "FE" ? task.scope : null;
  const fes = task.fes ?? [];
  const showFe = !scoped && !smeView && task.gps.some((g) => g.feName);
  const [feFilter, setFeFilter] = useState(ALL_FES);
  const [stage, setStage] = useState(ALL_STAGES);
  const roles = t.can.reviewAs ?? [];
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [rows, setRows] = useState<NewRow[]>([]);
  const [detailId, setDetailId] = useState<number | null>(null);
  const shown = task.gps.filter(
    (g) => (feFilter === ALL_FES || (feFilter === NO_FE ? !g.feName : g.feName === feFilter)) && (stage === ALL_STAGES || stageOf(g) === stage),
  );
  const selected = task.gps.filter((g) => picked.has(g.id));
  const canPick = shown.filter((g) => reviewable(g, roles));

  const changed = useMemo(
    () =>
      task.gps.flatMap((g) => {
        const d = draft[g.id];
        if (!d) return [];
        const remark = d.remark.trim();
        const remarkChanged = remark !== "" && remark !== (g.remarks ?? "");
        const category = d.category && d.category !== (g.gpCategory ?? null) ? d.category : null;
        const name = d.gpName !== undefined && d.gpName.trim().replace(/\s+/g, " ") !== g.gpName ? d.gpName.trim().replace(/\s+/g, " ") : undefined;
        const block = d.block !== undefined && (d.block.trim() || null) !== (g.block ?? null) ? d.block.trim() : undefined;
        const edited = name !== undefined || block !== undefined;
        return category || remarkChanged || d.files.length || edited
          ? [{ taskGpId: g.id, ...(category ? { category } : {}), remark: remark || null, ...(name !== undefined ? { gpName: name } : {}), ...(block !== undefined ? { block } : {}) }]
          : [];
      }),
    [draft, task.gps],
  );
  const proofs = useMemo(() => Object.entries(draft).flatMap(([id, d]) => d.files.map((file) => ({ taskGpId: Number(id), file }))), [draft]);
  const classified = changed.filter((c) => c.category).length;
  const edits = changed.filter((c) => "gpName" in c || "block" in c).length;
  const newGps: NewTaskGp[] = rows
    .filter((r) => r.gpCode.trim())
    .map((r) => ({ gpCode: r.gpCode.trim(), gpName: r.gpName.trim() || undefined, block: r.block.trim() || undefined, category: r.category ?? undefined, remark: r.remark.trim() || undefined }));
  const badRow = rows.find((r) => r.gpCode.trim() && !GP_CODE.test(r.gpCode.trim()));
  const emptyName = changed.some((c) => "gpName" in c && !c.gpName);

  const set = (id: number, patch: Partial<Draft[number]>) =>
    setDraft((cur) => {
      const g = task.gps.find((x) => x.id === id)!;
      const base = cur[id] ?? { category: null, remark: g.remarks ?? "", files: [] };
      return { ...cur, [id]: { ...base, ...patch } };
    });

  const addFiles = (id: number, list: FileList | null) => {
    const g = task.gps.find((x) => x.id === id)!;
    const have = draft[id]?.files ?? [];
    const picked = Array.from(list ?? []);
    const big = picked.find((f) => f.size > MAX_FILE_MB * 1024 * 1024);
    if (big) return setError(`${big.name}: larger than ${MAX_FILE_MB} MB`);
    if (have.length + picked.length > MAX_GP_FILES) return setError(`GP ${g.gpCode}: at most ${MAX_GP_FILES} proof documents per submission`);
    setError(null);
    set(id, { files: [...have, ...picked] });
  };

  const submit = async () => {
    setBusy(true);
    setSent(proofs.length ? 0 : null);
    setError(null);
    try {
      const next = await ticketApi.submitProgressForm(t.id, changed, note.trim() || undefined, proofs, proofs.length ? (f) => setSent(f) : undefined, newGps);
      setDraft({});
      setRows([]);
      setNote("");
      onChanged(next, {
        ok: true,
        text: `Daily progress saved: ${classified} GP status${classified === 1 ? "" : "es"} updated, ${changed.length} GP line${changed.length === 1 ? "" : "s"}${proofs.length ? `, ${proofs.length} proof document${proofs.length === 1 ? "" : "s"}` : ""}${newGps.length ? `, ${newGps.length} GP${newGps.length === 1 ? "" : "s"} added` : ""}${edits ? `, ${edits} GP${edits === 1 ? "" : "s"} corrected` : ""}. ${scoped ? "Your Area Manager and the admin have" : "The admin has"} been notified.`,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the daily progress");
    } finally {
      setBusy(false);
      setSent(null);
    }
  };

  const T = task.totals;
  return (
    <Card className="overflow-hidden p-0">
      {/* header: who / which week, downloads */}
      <div className="flex flex-col gap-3 border-b border-border px-5 py-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-base font-bold text-subheading">
            <ListChecks className="size-4 text-primary" aria-hidden /> GP-wise Weekly Task
            {scoped && <span className="rounded-full bg-primary-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-primary">Your GPs only</span>}
            {smeView && (
              <span className="rounded-full bg-primary-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-primary">
                GPs forwarded to you by the {reviewer === "COH" ? "SME" : "Area Manager"}
              </span>
            )}
          </h3>
          <p className="text-[0.8125rem] text-muted-foreground">
            {scoped && (
              <>
                FE <b className="font-semibold text-foreground">{scoped.fieldEngineer}</b> · Area Manager{" "}
              </>
            )}
            {smeView && <>Ticket {t.code} · Area Manager </>}
            <b className="font-semibold text-foreground">{task.areaManager}</b>
            {task.circle && <> · {task.circle}</>}
            {task.cbhName && <> · CBH {task.cbhName}</>} · {task.week.id.replace("W-", "Week ")} ({dm(task.week.start)} – {dm(task.week.end)}) · targets from {task.sourceFile}, data as of {ticketDay(task.dataAsOf)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <a href={ticketApi.taskWorkbookUrl(t.id, "assignment")} download>
              <FileSpreadsheet /> {scoped || smeView ? "My Assignment Excel" : "Assignment Excel"}
            </a>
          </Button>
          <Button asChild size="sm" variant="outline">
            <a href={ticketApi.taskWorkbookUrl(t.id, "progress")} download>
              <Download /> {scoped || smeView ? "My latest Excel" : "Download latest Excel"}
            </a>
          </Button>
        </div>
      </div>

      {/* SME / COH: the ticket's GPs against the GPs handed to them */}
      {kpis && reviewer && (
        <div className="grid grid-cols-2 gap-3 border-b border-border px-5 py-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Total GPs in Ticket" value={kpis.ticketGps} sub="all GPs of the Area Manager's ticket" />
          <Stat label="Assigned to You" value={kpis.assigned} cls="text-[var(--series-1)]" sub={reviewer === "SME" ? "approved & forwarded by the AM" : "reviewed & forwarded by the SME"} />
          <Stat label={reviewer === "SME" ? "Pending Your Review" : "Pending Letter Submission"} value={kpis.pending} cls={kpis.pending ? "text-warning-text" : undefined}
            sub={reviewer === "SME" && kpis.returnedToYou ? `${kpis.returnedToYou} sent back by the COH` : undefined} />
          {reviewer === "SME" ? (
            <Stat label="Forwarded to COH" value={kpis.forwarded ?? 0} cls="text-good-text" />
          ) : (
            <>
              <Stat label="Letter Submitted" value={kpis.letterSubmitted ?? 0} cls="text-good-text" />
              <Stat label="AMC Converted" value={kpis.amcConverted ?? 0} cls="text-good-text" />
            </>
          )}
          <Stat label={reviewer === "SME" ? "Sent Back to AM" : "Sent Back to SME"} value={kpis.sentBack} cls={kpis.sentBack ? "text-critical-text" : undefined} />
        </div>
      )}

      {/* totals + progress */}
      {!(kpis && reviewer) && (
      <div className="grid grid-cols-2 gap-3 border-b border-border px-5 py-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Assigned GPs" value={T.gps} sub={`${T.weekGps} this week · ${T.pendingGps} pending`} />
        <Stat label="Weekly Target" value={T.target} cls="text-[var(--series-1)]" />
        <Stat label="Achieved" value={T.achieved} cls="text-good-text" sub={`${T.doneGps} Done · ${T.openGps} Pending · ${T.proofFiles} proof file${T.proofFiles === 1 ? "" : "s"}`} />
        <Stat label="Remaining Gap" value={T.gap} cls={T.gap > 0 ? "text-critical-text" : "text-good-text"} />
        <div className="col-span-2 flex flex-col justify-center">
          <div className="flex items-baseline justify-between text-[0.75rem]">
            <span className="font-medium text-muted-foreground">Achievement</span>
            <span className="tabular text-base font-bold text-good-text">{T.pct == null ? "NA" : `${T.pct.toFixed(1)}%`}</span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${T.achieved} of ${T.target} GPs achieved`}>
            <div className="h-full rounded-full bg-good transition-[width] duration-500" style={{ width: `${Math.min(100, T.pct ?? 0)}%` }} />
          </div>
          <p className="mt-1 text-[0.6875rem] text-muted-foreground">Latest submission: {task.latestSubmission ? ticketTime(task.latestSubmission) : "none yet"}</p>
        </div>
      </div>
      )}

      {/* admin: block-wise performance */}
      {admin && task.blocks.length > 1 && (
        <div className="border-b border-border px-5 py-3">
          <p className="mb-2 text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">Block-wise</p>
          <div className="flex flex-wrap gap-2">
            {task.blocks.map((b) => (
              <span key={b.block} className="rounded-md border border-border px-2.5 py-1 text-[0.75rem]">
                <b>{b.block}</b> · {b.achieved}/{b.target} <span className={cn("font-semibold", b.gap > 0 ? "text-critical-text" : "text-good-text")}>gap {b.gap}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* review chain: where the GPs are */}
      {T.review && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-2.5 text-[0.75rem]">
          <span className="font-semibold uppercase tracking-wide text-muted-foreground">Review</span>
          {(
            [
              ["Pending AM Verification", T.review.awaiting, "PENDING_AM"],
              ["Returned to FE", T.review.returned, "RETURNED"],
              ["AM Approved – Pending SME Review", T.review.amApproved, "AM_APPROVED"],
              ["Returned to AM by SME", T.review.smeReturned ?? 0, "SME_RETURNED"],
              ["SME Reviewed – Forwarded to COH", T.review.smeForwarded, "SME_FORWARDED"],
              ["Returned to SME by COH", T.review.cohReturned ?? 0, "COH_RETURNED"],
              ["Letter Submitted", T.review.letterSubmitted, "LETTER_SUBMITTED"],
              ["AMC Converted", T.review.amcConverted, "AMC_CONVERTED"],
            ] as [string, number, GpStage][]
          ).map(([label, n, key]) => (
            <span key={label} className={cn("rounded-full px-2 py-0.5 font-semibold", REVIEW_STAGE[key].cls)}>
              {label} {n}
            </span>
          ))}
          {!!T.review.ndOpen && <span className="rounded-full bg-warning-soft px-2 py-0.5 font-semibold text-warning-text">Non-Doable cases open {T.review.ndOpen}</span>}
          {!!T.review.ndApproved && <span className={cn("rounded-full px-2 py-0.5 font-semibold", REVIEW_STAGE.ND_APPROVED.cls)}>Closed – Non-Doable {T.review.ndApproved}</span>}
          {!!T.addedGps && <span className="rounded-full bg-muted px-2 py-0.5 font-semibold text-muted-foreground">Added GPs {T.addedGps}</span>}
        </div>
      )}

      {/* Area Manager / admin: FE-wise allocation and progress */}
      {showFe && <FeSplit fes={fes} />}

      {!smeView && (
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-2.5 text-[0.78125rem]">
        <span className="font-medium text-muted-foreground">Show GPs</span>
        {showFe && (
          <Select
            ariaLabel="Field Engineer"
            value={feFilter}
            onValueChange={(v) => v && setFeFilter(v)}
            options={[
              { value: ALL_FES, label: "All Field Engineers" },
              ...fes.filter((f) => f.name).map((f) => ({ value: f.name!, label: `FE ${f.name}` })).filter((o, i, a) => a.findIndex((x) => x.value === o.value) === i),
              ...(fes.some((f) => !f.name) ? [{ value: NO_FE, label: "FE not mapped" }] : []),
            ]}
            className="w-60"
          />
        )}
        <Select
          ariaLabel="Review stage"
          value={stage}
          onValueChange={(v) => v && setStage(v)}
          options={[{ value: ALL_STAGES, label: "All review stages" }, ...Object.entries(REVIEW_STAGE).map(([k, v]) => ({ value: k, label: v.label }))]}          className="w-52"
        />
        <span className="text-muted-foreground">
          {shown.length} of {task.gps.length} GPs
        </span>
      </div>
      )}

      {roles.length > 0 && t.status !== "CLOSED" && <ReviewBar t={t} roles={roles} selected={selected} onClear={() => setPicked(new Set())} onChanged={onChanged} />}

      {/* SME: only the GPs forwarded to them, FE submission and AM approval side by side */}
      {reviewer && <SmeGpTable t={t} kind={reviewer} roles={roles} picked={picked} setPicked={setPicked} onChanged={onChanged} />}

      {/* GP-wise progress table (scrolls inside the card; the header stays visible) */}
      {!smeView && (
      <div className="max-h-[35rem] overflow-auto">
        <table className="w-full min-w-[90rem] text-[0.8125rem]">
          <caption className="sr-only">GP-wise task progress</caption>
          <thead className="sticky top-0 z-10">
            <tr className="border-b border-border bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
              {roles.length > 0 && (
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
              )}
              {["GP Code", "GP Name", "Block", ...(showFe ? ["FE"] : []), "Type", "Weekly Target", "Achieved", "Remaining Gap", "Daily Achievement", "Remarks", "Proof", "Review", "Action"].map((h) => (
                <th key={h} scope="col" className={cn("px-3 py-2", ["Weekly Target", "Achieved", "Remaining Gap"].includes(h) && "text-right", ["Daily Achievement", "Action"].includes(h) && "text-center")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {shown.map((g) => {
              const d = draft[g.id];
              const done = g.status === "DONE";
              const cat = d?.category ?? g.gpCategory ?? null;
              // achieved as it will be after the submission: only E counts (plus an AMC Date in the master data)
              const cum = d?.category ? Math.min(g.target, g.baseAchieved + (d.category === "E" ? 1 : 0)) : g.cumulative;
              const rowEdit = editable && !g.locked && !g.ndCase?.open; // approved by the Area Manager / in a Non-Doable case = no daily changes
              const pickable = reviewable(g, roles);
              return (
                <tr key={g.id} className={cn("border-b border-border/70 last:border-0", d && "bg-primary-soft/30", g.review === "RETURNED" && !d && "bg-critical-soft/30")}>
                  {roles.length > 0 && (
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label={`Select ${g.gpCode} for review`}
                        disabled={!pickable}
                        checked={picked.has(g.id)}
                        onChange={(e) =>
                          setPicked((cur) => {
                            const next = new Set(cur);
                            if (e.target.checked) next.add(g.id);
                            else next.delete(g.id);
                            return next;
                          })
                        }
                        className="size-4 accent-[var(--primary)] disabled:opacity-30"
                      />
                    </td>
                  )}
                  <td className="px-3 py-2">
                    <button type="button" onClick={() => setDetailId(g.id)} className="font-semibold text-primary hover:underline" title="Open the GP details (FE submission, AM approval, review history)">
                      {g.gpCode}
                    </button>
                  </td>
                  <td className="min-w-[10.625rem] px-3 py-1.5">
                    {rowEdit ? (
                      <Input value={d?.gpName ?? g.gpName} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { gpName: e.target.value })} className="h-8 text-[0.8125rem]" aria-label={`GP name of ${g.gpCode}`} />
                    ) : (
                      g.gpName
                    )}
                  </td>
                  <td className="min-w-[8.125rem] px-3 py-1.5 text-muted-foreground">
                    {rowEdit ? (
                      <Input value={d?.block ?? g.block ?? ""} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { block: e.target.value })} className="h-8 text-[0.8125rem]" placeholder="Block" aria-label={`Block of ${g.gpCode}`} />
                    ) : (
                      (g.block ?? "—")
                    )}
                  </td>
                  {showFe && <td className={cn("px-3 py-2", !g.feName && "text-warning-text")}>{g.feName ?? "Not mapped"}</td>}
                  <td className="px-3 py-2">
                    <span
                      className={cn("rounded px-1.5 py-0.5 text-[0.6875rem] font-semibold", g.kind === "WEEK" ? "bg-primary-soft text-primary" : g.kind === "ADDED" ? "bg-muted text-foreground" : "bg-warning-soft text-warning-text")}
                      title={g.kind === "ADDED" ? `Added by ${g.addedBy ?? "the FE"}` : g.plannedDate ? `Planned ${ticketDay(g.plannedDate)}` : undefined}
                    >
                      {g.kind === "WEEK" ? "Week" : g.kind === "ADDED" ? "Added" : "Pending"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-semibold">{g.target}</td>
                  <td
                    className={cn("px-3 py-2 text-right font-semibold", cum >= g.target && "text-good-text")}
                    title={g.baseAchieved ? `Already achieved at assignment (AMC Date ${g.amcDate ? ticketDay(g.amcDate) : ""} in the master data)` : cum ? `${CATEGORY.E.label} in the daily progress` : undefined}
                  >
                    {cum}
                  </td>
                  <td className={cn("px-3 py-2 text-right font-semibold", g.target - cum > 0 ? "text-critical-text" : "text-good-text")}>{g.target - cum}</td>
                  <td className="px-3 py-1.5 text-center">
                    {rowEdit ? (
                      <GpCategorySelect value={cat} disabled={busy} onChange={(v) => set(g.id, { category: v === (g.gpCategory ?? null) ? null : v })} ariaLabel={`Daily achievement of ${g.gpCode}`} />
                    ) : cat || !done ? (
                      <GpCategoryBadge code={cat} />
                    ) : (
                      <GpStatusBadge status={g.status} />
                    )}
                  </td>
                  <td className="min-w-[12.5rem] px-3 py-1.5">
                    {rowEdit ? (
                      <Input value={d?.remark ?? g.remarks ?? ""} maxLength={500} disabled={busy} onChange={(e) => set(g.id, { remark: e.target.value })} placeholder={done ? "Remark" : "Remark / reason if pending"} className="h-8 text-[0.8125rem]" aria-label={`Remark for ${g.gpCode}`} />
                    ) : (
                      <span className="text-[0.8125rem]">{g.remarks ?? <span className="text-muted-foreground">No Remarks</span>}</span>
                    )}
                  </td>
                  <td className="min-w-[11.875rem] max-w-[15rem] px-3 py-1.5">
                    {g.files.length > 0 && <ProofList files={g.files} compact />}
                    {d?.files.map((f, i) => (
                      <span key={`${f.name}-${i}`} className="mt-0.5 flex items-center gap-1 text-[0.75rem] text-[var(--series-7)]">
                        <Paperclip className="size-3.5 shrink-0" aria-hidden />
                        <span className="min-w-0 flex-1 truncate" title={`${f.name} (${fileSize(f.size)}) – sent with the next submission`}>
                          {f.name}
                        </span>
                        <button type="button" disabled={busy} onClick={() => set(g.id, { files: d.files.filter((_, j) => j !== i) })} className="rounded p-0.5 hover:bg-accent" aria-label={`Remove ${f.name}`}>
                          <X className="size-3" />
                        </button>
                      </span>
                    ))}
                    {rowEdit ? (
                      <label className={cn("mt-0.5 inline-flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 text-[0.75rem] font-medium text-primary hover:bg-primary-soft", busy && "pointer-events-none opacity-50")}>
                        <Paperclip className="size-3.5" aria-hidden /> Attach
                        <input
                          type="file"
                          multiple
                          accept={PROOF_ACCEPT}
                          className="sr-only"
                          disabled={busy}
                          onChange={(e) => {
                            addFiles(g.id, e.target.files);
                            e.target.value = "";
                          }}
                          aria-label={`Attach proof for ${g.gpCode}`}
                        />
                      </label>
                    ) : (
                      g.files.length === 0 && <span className="text-[0.75rem] text-muted-foreground">Proof Not Uploaded</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5">
                    <ReviewCell g={g} />
                  </td>
                  <td className="px-3 py-2 text-center">
                    {rowEdit && d ? (
                      <button
                        type="button"
                        className="rounded px-1.5 py-0.5 text-[0.75rem] font-medium text-primary hover:bg-primary-soft disabled:opacity-50"
                        disabled={busy}
                        onClick={() => setDraft((cur) => Object.fromEntries(Object.entries(cur).filter(([k]) => Number(k) !== g.id)))}
                        title="Undo the unsubmitted change of this GP"
                      >
                        Clear
                      </button>
                    ) : (
                      <span className="text-[0.6875rem] text-muted-foreground" title={g.lastUpdated ? `Last updated ${ticketTime(g.lastUpdated)}${g.lastUpdatedBy ? ` by ${g.lastUpdatedBy}` : ""}` : undefined}>
                        {g.lastUpdated ? ticketDay(g.lastUpdated) : "—"}
                        {g.lastUpdatedBy && <span className="block font-medium text-foreground/80">by {g.lastUpdatedBy}</span>}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      )}
      {!smeView && <GpDetailDialog t={t} g={task.gps.find((g) => g.id === detailId) ?? null} roles={roles} onClose={() => setDetailId(null)} onChanged={onChanged} />}

      {/* GP rows added by the FE / Area Manager (target 1 each, sent with the submission) */}
      {editable && (
        <div className="border-t border-border px-5 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">
              Add GPs <span className="font-normal normal-case">– a GP missing from the list; its details come from the master data when the code is known (target 1 each)</span>
            </p>
            <Button
              size="sm"
              variant="outline"
              disabled={busy || rows.length >= 50}
              onClick={() => setRows((cur) => [...cur, { key: Date.now() + cur.length, gpCode: "", gpName: "", block: "", category: null, remark: "" }])}
            >
              <Plus /> Add GP row
            </Button>
          </div>
          {rows.length > 0 && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[60rem] text-[0.8125rem]">
                <thead>
                  <tr className="text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                    {["GP Code", "GP Name", "Block", "Daily Achievement", "Remarks", ""].map((h) => (
                      <th key={h} scope="col" className="px-2 py-1">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const upd = (patch: Partial<NewRow>) => setRows((cur) => cur.map((x) => (x.key === r.key ? { ...x, ...patch } : x)));
                    const bad = r.gpCode.trim() !== "" && !GP_CODE.test(r.gpCode.trim());
                    return (
                      <tr key={r.key} className="border-t border-border/60">
                        <td className="px-2 py-1.5">
                          <Input value={r.gpCode} maxLength={40} disabled={busy} onChange={(e) => upd({ gpCode: e.target.value })} placeholder="GP code" aria-invalid={bad} className={cn("h-8 w-36 text-[0.8125rem]", bad && "border-critical")} aria-label="New GP code" />
                        </td>
                        <td className="px-2 py-1.5">
                          <Input value={r.gpName} maxLength={160} disabled={busy} onChange={(e) => upd({ gpName: e.target.value })} placeholder="GP name (if not in master data)" className="h-8 text-[0.8125rem]" aria-label="New GP name" />
                        </td>
                        <td className="px-2 py-1.5">
                          <Input value={r.block} maxLength={160} disabled={busy} onChange={(e) => upd({ block: e.target.value })} placeholder="Block" className="h-8 w-40 text-[0.8125rem]" aria-label="New GP block" />
                        </td>
                        <td className="px-2 py-1.5">
                          <GpCategorySelect value={r.category} disabled={busy} onChange={(v) => upd({ category: v as NewRow["category"] })} ariaLabel="Daily achievement of the new GP" />
                        </td>
                        <td className="px-2 py-1.5">
                          <Input value={r.remark} maxLength={500} disabled={busy} onChange={(e) => upd({ remark: e.target.value })} placeholder="Remark" className="h-8 text-[0.8125rem]" aria-label="New GP remark" />
                        </td>
                        <td className="px-2 py-1.5 text-right">
                          <button type="button" disabled={busy} onClick={() => setRows((cur) => cur.filter((x) => x.key !== r.key))} className="rounded p-1 hover:bg-accent" aria-label="Remove this GP row">
                            <X className="size-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* submit (Area Manager / FE) */}
      {editable && (
        <div className="flex flex-col gap-3 border-t border-border px-5 py-4 lg:flex-row lg:items-end">
          <label className="flex-1 space-y-1">
            <span className="text-[0.8125rem] font-medium">Note for today (optional)</span>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={2000} disabled={busy} className={TEXTAREA} placeholder="What was done today…" />
          </label>
          <div className="flex flex-col items-end gap-1">
            <span className="text-xs text-muted-foreground">
              {sent !== null
                ? `Uploading proof documents… ${Math.round(sent * 100)}%`
                : badRow
                  ? `"${badRow.gpCode.trim()}" is not a valid GP code`
                  : emptyName
                    ? "A GP name cannot be empty"
                    : changed.length || newGps.length
                      ? `${classified} status change${classified === 1 ? "" : "s"} · ${edits} corrected · ${changed.length - classified} other line${changed.length - classified === 1 ? "" : "s"} · ${proofs.length} proof file${proofs.length === 1 ? "" : "s"} · ${newGps.length} new GP${newGps.length === 1 ? "" : "s"}`
                      : "Choose a status for the GPs, correct their details, write a remark, attach proof or add a GP"}
            </span>
            <Button variant="primary" onClick={submit} disabled={busy || (changed.length === 0 && newGps.length === 0) || !!badRow || emptyName}>
              {busy ? <Loader2 className="animate-spin" /> : <Send />} Submit Daily Progress
            </Button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="mx-5 mb-4 rounded-md border border-critical/30 bg-critical-soft px-4 py-2.5 text-sm text-critical-text">
          {error}
        </p>
      )}
      {t.status === "CLOSED" && <p className="border-t border-border px-5 py-3 text-[0.8125rem] text-muted-foreground">The ticket is closed – daily progress is read-only.</p>}

      <ProgressHistory task={task} />
    </Card>
  );
}

/** FE-wise allocation and progress of the task (Area Manager, CBH / SME and admin view). */
function FeSplit({ fes }: { fes: NonNullable<TicketTask["fes"]> }) {
  return (
    <div className="border-b border-border px-5 py-3">
      <p className="mb-2 text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">Field Engineer-wise</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[87.5rem] text-[0.78125rem]">
          <thead>
            <tr className="text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
              {["Field Engineer", "GPs", "Target", "Achieved", "Gap"].map((h) => (
                <th key={h} scope="col" className={cn("px-2 py-1", h !== "Field Engineer" && "text-right")}>
                  {h}
                </th>
              ))}
              {GP_CATEGORIES.map((c) => (
                <th key={c.code} scope="col" className="px-2 py-1 text-right" title={c.label}>
                  <span className="inline-flex items-center gap-1">
                    <span className="size-1.5 rounded-full" style={{ background: c.color }} aria-hidden />
                    {c.label}
                  </span>
                </th>
              ))}
              {["Not classified", "Awaiting AM", "Approved", "Returned", "Added", "Proof files", "Last update"].map((h) => (
                <th key={h} scope="col" className={cn("px-2 py-1", h !== "Last update" && "text-right")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {fes.map((f) => (
              <tr key={`${f.name ?? "-"}|${f.email ?? ""}`} className="border-t border-border/60">
                <td className="px-2 py-1.5">
                  {f.name ? (
                    <>
                      <b className="font-semibold">{f.name}</b>
                      {f.email && <span className="text-muted-foreground"> · {f.email}</span>}
                      {!f.recipient && <span className="ml-1.5 rounded bg-muted px-1.5 py-0.5 text-[0.65625rem] font-semibold text-muted-foreground">not on this ticket</span>}
                    </>
                  ) : (
                    <span className="text-warning-text">FE not mapped in the Escalation Matrix</span>
                  )}
                </td>
                <td className="px-2 py-1.5 text-right">{f.gps}</td>
                <td className="px-2 py-1.5 text-right">{f.target}</td>
                <td className="px-2 py-1.5 text-right font-semibold text-good-text">{f.achieved}</td>
                <td className={cn("px-2 py-1.5 text-right font-semibold", f.gap > 0 ? "text-critical-text" : "text-good-text")}>{f.gap}</td>
                {GP_CATEGORIES.map((c) => (
                  <td key={c.code} className="px-2 py-1.5 text-right font-semibold" style={f.categories?.[c.code] ? { color: c.color } : undefined}>
                    {f.categories?.[c.code] ?? 0}
                  </td>
                ))}
                <td className="px-2 py-1.5 text-right text-muted-foreground">{f.notClassified ?? f.gps}</td>
                <td className={cn("px-2 py-1.5 text-right", f.awaitingGps ? "font-semibold text-warning-text" : "text-muted-foreground")}>{f.awaitingGps ?? 0}</td>
                <td className={cn("px-2 py-1.5 text-right", f.approvedGps ? "font-semibold text-good-text" : "text-muted-foreground")}>{f.approvedGps ?? 0}</td>
                <td className={cn("px-2 py-1.5 text-right", f.returnedGps ? "font-semibold text-critical-text" : "text-muted-foreground")}>{f.returnedGps ?? 0}</td>
                <td className="px-2 py-1.5 text-right text-muted-foreground">{f.addedGps ?? 0}</td>
                <td className="px-2 py-1.5 text-right">{f.proofFiles}</td>
                <td className="px-2 py-1.5 text-muted-foreground">{f.lastUpdated ? ticketDay(f.lastUpdated) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Stat({ label, value, sub, cls }: { label: string; value: number; sub?: string; cls?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("tabular text-[1.125rem] font-bold leading-tight", cls ?? "text-heading")}>{formatCount(value)}</p>
      {sub && <p className="text-[0.6875rem] text-muted-foreground">{sub}</p>}
    </div>
  );
}

/** Date-wise history of the daily submissions (newest first), each with its GP lines. */
function ProgressHistory({ task }: { task: TicketTask }) {
  const [open, setOpen] = useState<number | null>(task.history[0]?.id ?? null);
  const [who, setWho] = useState("__all");
  const people = [...new Set(task.history.map((h) => h.submittedBy))];
  const shown = task.history.filter((h) => who === "__all" || h.submittedBy === who);
  return (
    <div className="border-t border-border px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-[0.875rem] font-bold text-subheading">Daily Progress History</h4>
        {people.length > 1 && (
          <span className="flex items-center gap-2 text-[0.78125rem]">
            <span className="text-muted-foreground">Submitted by</span>
            <Select ariaLabel="Submitted by" value={who} onValueChange={(v) => v && setWho(v)} options={[{ value: "__all", label: "Everyone" }, ...people.map((p) => ({ value: p, label: p }))]} className="h-8 w-56" />
          </span>
        )}
      </div>
      {task.history.length === 0 ? (
        <p className="mt-1 text-[0.8125rem] text-muted-foreground">No daily progress submitted yet.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {shown.map((h) => {
            const isOpen = open === h.id;
            const done = h.lines.reduce((s, l) => s + l.achievedToday, 0);
            return (
              <li key={h.id} className="rounded-lg border border-border">
                <button type="button" onClick={() => setOpen(isOpen ? null : h.id)} aria-expanded={isOpen} className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left">
                  <span className="text-[0.8125rem]">
                    <b>{ticketTime(h.submittedAt)}</b> · {h.submittedBy} · {done} Done · {h.lines.length} line{h.lines.length === 1 ? "" : "s"}
                    {h.lines.some((l) => l.files.length) && ` · ${h.lines.reduce((n, l) => n + l.files.length, 0)} proof`}
                    {h.note && <span className="text-muted-foreground"> · {h.note}</span>}
                  </span>
                  <ChevronDown className={cn("size-4 shrink-0 transition-transform", isOpen && "rotate-180")} aria-hidden />
                </button>
                {isOpen && (
                  <div className="overflow-x-auto border-t border-border">
                    <table className="w-full min-w-[56.25rem] text-[0.78125rem]">
                      <thead>
                        <tr className="bg-muted/50 text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                          {["GP Code", "GP Name", "Block", "Daily Achievement", "Status", "Cumulative", "Gap", "Remark", "Proof"].map((x) => (
                            <th key={x} scope="col" className={cn("px-3 py-1.5", ["Daily Achievement", "Cumulative", "Gap"].includes(x) && "text-right")}>
                              {x}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="tabular">
                        {h.lines.map((l, i) => (
                          <tr key={i} className="border-t border-border/60">
                            <td className="px-3 py-1.5 font-medium">{l.gpCode}</td>
                            <td className="px-3 py-1.5">{l.gpName}</td>
                            <td className="px-3 py-1.5 text-muted-foreground">{l.block ?? "—"}</td>
                            <td className={cn("px-3 py-1.5 text-right font-semibold", l.achievedToday ? "text-good-text" : "text-muted-foreground")}>{l.achievedToday}</td>
                            <td className="px-3 py-1.5">{l.gpCategory ? <GpCategoryBadge code={l.gpCategory} /> : <GpStatusBadge status={l.status} />}</td>
                            <td className="px-3 py-1.5 text-right">{l.cumulative}</td>
                            <td className={cn("px-3 py-1.5 text-right", l.gap > 0 ? "text-critical-text" : "text-good-text")}>{l.gap}</td>
                            <td className="px-3 py-1.5">{l.remark ?? "—"}</td>
                            <td className="max-w-[13.75rem] px-3 py-1.5">
                              <ProofList files={l.files} compact emptyText="—" />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
