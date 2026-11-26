"use client";

import { Camera, CheckCircle2, ChevronDown, Download, FileSpreadsheet, ListChecks, Loader2, MapPin, OctagonAlert, Paperclip, Plus, Send, Undo2, UserCog, X } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { ticketApi, type FeCheckAction, type GeoFile, type GpCategory, type GpReviewAction, type NewTaskGp, type TicketDetail, type TicketTask, type TicketTaskFrt, type TicketTaskGp } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";
import { TEXTAREA, fileSize, ticketDay, ticketTime, type Notice } from "./ticket-parts";
import { CATEGORY, GpCategoryBadge, GpCategorySelect } from "./gp-category";
import { CameraCapture } from "./camera-capture";
import { AM_TABS, AmSummary, amBucket, type AmTab } from "./am-task-parts";
import { FeSummary, TagCell, TypeTag } from "./fe-task-parts";
import { FrtCheckBadge, FrtProofChips, FrtSteps, FrtSummary } from "./frt-task-parts";
import { CohReviewTable } from "./coh-review-table";
import { GpDetailDialog } from "./gp-detail";
import { GpTicketId } from "./ticket-hierarchy";
import { useReviewerNdCases, ndPendingFor } from "./nd-gp-rows";
import { SmeReviewTable } from "./sme-review-table";
import { NdFillDialog, TicketNdCases } from "./non-doable-view";
import { GpStatusBadge, PROOF_ACCEPT, ProofList } from "./ticket-proof";
import { REVIEW_STAGE, ReviewBar, ReviewCell, ReviewDialog, canStep, reviewable, stageOf } from "./ticket-review";

const dm = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "UTC" });
const MAX_GP_FILES = 5; // per GP and submission (backend: task.MAX_GP_FILES)
const MAX_FILE_MB = 20; // per file (backend: TICKET_FILE_MAX_MB)
const ALL_FES = "__all";
const NO_FE = "__none";

const ALL_STAGES = "__all";
const GP_CODE = /^[A-Za-z0-9][A-Za-z0-9/_.-]{0,39}$/; // backend: task.GP_CODE_RE
// Daily Achievement evidence (backend: task.MIN_REMARK / PHOTO_EXTS): a remark and at least one photo per GP
const MIN_REMARK = 3;
const isPhoto = (f: File) => /\.(jpe?g|png)$/i.test(f.name);
// the FRT on a phone: a live Camera photo with its location; on a laptop: an uploaded photo file (backend accepts both)
const isCameraPhoto = (f: File) => isPhoto(f) && !!(f as GeoFile).geo;
const PHONE_QUERY = "(pointer: coarse)"; // phone / tablet (touch screen) – the Camera; mouse = laptop / desktop – file upload
const subscribePhone = (cb: () => void) => {
  const m = window.matchMedia(PHONE_QUERY);
  m.addEventListener("change", cb);
  return () => m.removeEventListener("change", cb);
};
const useIsPhone = () => useSyncExternalStore(subscribePhone, () => window.matchMedia(PHONE_QUERY).matches, () => false);
const CAMERA_HINT = "Remark + Camera photo (with location) required";
const EVIDENCE_HINT = "Remark + photo (JPG / PNG) required";

/** Unsubmitted change of a GP: Daily Achievement category (A / C / D, null = unchanged), remark, proof files to attach,
 * corrected GP Name / Block (undefined = unchanged). */
type Draft = Record<number, { category: GpCategory | null; remark: string; files: File[]; gpCode?: string; gpName?: string; block?: string }>;
/** A GP row added by the FE / Area Manager, sent with the next submission (with its photos). */
type NewRow = { key: number; gpCode: string; gpName: string; block: string; category: "A" | "C" | "D" | null; remark: string; files: File[] };

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
  // FRT: Non-Doable cases shown in the E1 / E2 popup (just = opened by the Daily Achievement just submitted)
  const [ndFill, setNdFill] = useState<{ ids: number[]; just: boolean } | null>(null);
  const [sent, setSent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // FE / FRT view = only their GPs; SME view = only the GPs the Area Manager forwarded to this SME (cut by the backend)
  const reviewer = task.scope && (task.scope.kind === "SME" || task.scope.kind === "COH") ? task.scope.kind : null; // "SME" | "COH" view
  const kpis = task.scope && (task.scope.kind === "SME" || task.scope.kind === "COH") ? task.scope.kpis : undefined;
  const smeView = reviewer !== null;
  // SME / COH: the ticket's Non-Doable cases handed to them – rows in their table and the "Non-Doable pending" card
  const ndCases = useReviewerNdCases(t.id, reviewer, t.updatedAt);
  const ndWaiting = reviewer ? ndCases.filter((c) => ndPendingFor(c, reviewer)).length : 0;
  const scoped = task.scope && task.scope.kind === "FE" ? task.scope : null;
  // FRT view: the FRT reports the Daily Achievement of their GPs, their FE verifies it before the Area Manager
  const frtScope = task.scope && task.scope.kind === "FRT" ? task.scope : null;
  // the FRT on a phone: Camera photo (with location) required; on a laptop: upload a photo file
  const isPhone = useIsPhone();
  // FRT and FE on a phone: the proof photo is a live Camera photo (location / date / time); laptop = file upload
  const camOnly = (!!frtScope || !!scoped) && isPhone;
  const fes = task.fes ?? [];
  const frts = task.frts ?? [];
  const showFe = !scoped && !frtScope && !smeView && task.gps.some((g) => g.feName);
  const showFrtCol = !frtScope && !smeView && task.gps.some((g) => g.frtCode);
  const [checking, setChecking] = useState<{ g: TicketTaskGp; action: FeCheckAction; all?: TicketTaskGp[] } | null>(null);
  const [feFilter, setFeFilter] = useState(ALL_FES);
  const [stage, setStage] = useState(ALL_STAGES);
  const roles = t.can.reviewAs ?? [];
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [rows, setRows] = useState<NewRow[]>([]);
  const [detailId, setDetailId] = useState<number | null>(null);
  const [camFor, setCamFor] = useState<TicketTaskGp | null>(null); // FRT: camera dialog of this GP
  const [feTab, setFeTab] = useState<"verify" | "own" | null>(null); // FE view: FRT reports to verify / own GPs
  const [feSel, setFeSel] = useState<Set<number>>(new Set()); // FE view: FRT reports picked for one Verify / Return
  const [amTab, setAmTab] = useState<AmTab | null>(null); // AM view: work tab (null = approval pending when any)
  const [amSearch, setAmSearch] = useState(""); // AM view: GP code / name / block / FRT search
  const [amAct, setAmAct] = useState<{ action: GpReviewAction; gps: TicketTaskGp[] } | null>(null); // AM view: one row's Approve / Return
  const [moving, setMoving] = useState<TicketTaskGp | null>(null);
  // Area Manager / admin: give a GP to another FE of the ticket (not once approved / in a Non-Doable case)
  const canReassign = !!t.can.reassign && !scoped && !frtScope && !smeView && (task.feOptions?.length ?? 0) > 0;
  // the FE (or an admin) checks the FRT's Daily Achievement: verify → Area Manager, or return → FRT (backend: task.fe_check)
  const canCheck = (scoped !== null || admin) && t.status !== "CLOSED";
  const canVerify = (g: TicketTaskGp) => canCheck && !g.locked && !g.ndCase?.open && g.frtStage === "PENDING_FE" && (!g.review || g.review === "RETURNED");
  const canReturnFrt = (g: TicketTaskGp) => canVerify(g) || (canCheck && !g.locked && !g.ndCase?.open && g.frtStage === "FE_VERIFIED" && g.review === "RETURNED");
  const showFeCol = showFe || canReassign;
  // Non-Doable cases waiting for this user's E1 / E2 forms: the Daily Achievement is locked until they are submitted
  const ndPending = editable ? (task.ndPending ?? []) : [];
  const shown = task.gps.filter(
    (g) => (feFilter === ALL_FES || (feFilter === NO_FE ? !g.feName : g.feName === feFilter)) && (stage === ALL_STAGES || stageOf(g) === stage),
  );
  const selected = task.gps.filter((g) => picked.has(g.id));
  // FE view (User Tickets): the FRT's reports to verify and the FE's own GPs (no FRT login) in two tabs, work first
  const feView = scoped !== null && !smeView;
  const feFrt = feView ? shown.filter((g) => g.frtAssigned) : [];
  const feOwn = feView ? shown.filter((g) => !g.frtAssigned) : [];
  const tab = feTab ?? (task.gps.some((g) => g.frtAssigned) ? "verify" : "own");
  const feRank = (g: TicketTaskGp) =>
    tab === "verify"
      ? g.frtStage === "PENDING_FE" ? 0 : g.review === "RETURNED" ? 1 : g.frtStage === "RETURNED_FRT" ? 2 : !g.gpCategory ? 3 : 4
      : g.review === "RETURNED" ? 0 : !g.gpCategory ? 1 : 2;
  const feRows = (tab === "verify" ? feFrt : feOwn).map((g, i) => [g, i] as const).sort((a, b) => feRank(a[0]) - feRank(b[0]) || a[1] - b[1]).map(([g]) => g);
  const feVerifiable = feFrt.filter((g) => canVerify(g));
  const feSelected = feVerifiable.filter((g) => feSel.has(g.id));
  // Area Manager view (User Tickets): GPs in work tabs by stage, approval pending first; search on code / name / block / FRT
  const amView = !admin && !scoped && !frtScope && !smeView && roles.includes("AM");
  const amQ = amSearch.trim().toLowerCase();
  const amShown = amView ? shown.filter((g) => !amQ || `${g.gpCode} ${g.gpName} ${g.block ?? ""} ${g.frtCode ?? ""} ${g.feName ?? ""}`.toLowerCase().includes(amQ)) : [];
  const amCount = (k: AmTab) => (k === "all" ? amShown.length : amShown.filter((g) => amBucket(g) === k).length);
  const amTabNow: AmTab = amTab ?? (task.gps.some((g) => amBucket(g) === "pending") ? "pending" : "all");
  const amRows = amShown.filter((g) => amTabNow === "all" || amBucket(g) === amTabNow);
  const amPickable = amRows.filter((g) => reviewable(g, roles));
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
        const code = d.gpCode !== undefined && d.gpCode.trim() !== g.gpCode ? d.gpCode.trim() : undefined;
        const edited = name !== undefined || block !== undefined || code !== undefined;
        return category || remarkChanged || d.files.length || edited
          ? [{ taskGpId: g.id, ...(category ? { category } : {}), remark: remark || null, ...(code !== undefined ? { gpCode: code } : {}), ...(name !== undefined ? { gpName: name } : {}), ...(block !== undefined ? { block } : {}) }]
          : [];
      }),
    [draft, task.gps],
  );
  const proofs = useMemo(() => Object.entries(draft).flatMap(([id, d]) => d.files.map((file) => ({ taskGpId: Number(id), file }))), [draft]);
  const classified = changed.filter((c) => c.category).length;
  const edits = changed.filter((c) => "gpName" in c || "block" in c || "gpCode" in c).length;
  const filledRows = rows.filter((r) => r.gpCode.trim());
  const newGps: NewTaskGp[] = filledRows.map((r) => ({ gpCode: r.gpCode.trim(), gpName: r.gpName.trim() || undefined, block: r.block.trim() || undefined, category: r.category ?? undefined, remark: r.remark.trim() || undefined }));
  // photos of an added GP: proofGps = -(its index + 1) in newGps (the backend links them once the GP exists)
  const allProofs = [...proofs, ...filledRows.flatMap((r, i) => r.files.map((file) => ({ taskGpId: -(i + 1), file })))];
  // Daily Achievement evidence: a new / changed category (or a returned GP sent back) needs a remark and a photo
  const byId = new Map(task.gps.map((g) => [g.id, g]));
  const lacking = [
    ...changed
      .filter((c) => c.category || byId.get(c.taskGpId)?.review === "RETURNED" || (!!frtScope && byId.get(c.taskGpId)?.frtStage === "RETURNED_FRT"))
      .filter((c) => (c.remark ?? "").trim().length < MIN_REMARK || !(draft[c.taskGpId]?.files ?? []).some(camOnly ? isCameraPhoto : isPhoto))
      .map((c) => byId.get(c.taskGpId)?.gpCode ?? String(c.taskGpId)),
    ...filledRows.filter((r) => r.category && (r.remark.trim().length < MIN_REMARK || !r.files.some(isPhoto))).map((r) => r.gpCode.trim()),
  ];
  const badRow = rows.find((r) => r.gpCode.trim() && !GP_CODE.test(r.gpCode.trim()));
  const emptyName = changed.some((c) => "gpName" in c && !c.gpName);
  // a corrected GP code: same format as an added GP (backend: task.GP_CODE_RE; duplicates are checked by the backend)
  const badCode = changed.find((c) => "gpCode" in c && !GP_CODE.test(String(c.gpCode)));

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
    setSent(allProofs.length ? 0 : null);
    setError(null);
    try {
      const next = await ticketApi.submitProgressForm(t.id, changed, note.trim() || undefined, allProofs, allProofs.length ? (f) => setSent(f) : undefined, newGps);
      // FRT: the Non-Doable cases this submission opened – their optional E1 / E2 in a popup right here
      if (frtScope) {
        const ids = (next.task?.gps ?? [])
          .filter((g) => g.ndCase?.open && (changed.some((c) => c.taskGpId === g.id && c.category === "D") || newGps.some((n) => n.category === "D" && n.gpCode === g.gpCode)))
          .map((g) => g.ndCase!.id);
        if (ids.length) setNdFill({ ids, just: true });
      }
      setDraft({});
      setRows([]);
      setNote("");
      onChanged(next, {
        ok: true,
        text: `Daily progress saved: ${classified} GP status${classified === 1 ? "" : "es"} updated, ${changed.length} GP line${changed.length === 1 ? "" : "s"}${proofs.length ? `, ${proofs.length} proof document${proofs.length === 1 ? "" : "s"}` : ""}${newGps.length ? `, ${newGps.length} GP${newGps.length === 1 ? "" : "s"} added` : ""}${edits ? `, ${edits} GP${edits === 1 ? "" : "s"} corrected` : ""}. ${frtScope ? "Your FE verifies it and sends it to the Area Manager." : scoped ? "Your Area Manager and the admin have been notified." : "The admin has been notified."}`,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the daily progress");
    } finally {
      setBusy(false);
      setSent(null);
    }
  };

  /** A camera photo (with its location / time) goes with the GP's next submission. */
  const addCameraFile = (id: number, file: GeoFile) => {
    const have = draft[id]?.files ?? [];
    if (have.length >= MAX_GP_FILES) return setError(`At most ${MAX_GP_FILES} proof documents per GP and submission`);
    setError(null);
    set(id, { files: [...have, file] });
  };

  /** The rules of one GP row – the same for the table (desktop) and the cards (phone). */
  const info = (g: TicketTaskGp) => {
    const d = draft[g.id];
    const done = g.status === "DONE";
    const cat = d?.category ?? g.gpCategory ?? null;
    // achieved as it will be after the submission: only E counts (plus an AMC Date in the master data)
    const cum = d?.category ? Math.min(g.target, g.baseAchieved + (d.category === "E" ? 1 : 0)) : g.cumulative;
    // approved by the Area Manager / in a Non-Doable case = no daily changes; an FE's GP is reported by the FE only
    // (the Area Manager reviews it), an FRT's GP by the FRT only (the FE verifies it) – same rules as the backend
    // a GP with an FRT login: once the FRT reported it the FE only verifies / returns it; while the FRT has reported
    // nothing (no FRT stage) the FE may report it itself, straight to the Area Manager (backend: task.submit_progress)
    const rowEdit =
      editable && !g.locked && !g.ndCase?.open && !(scoped !== null && g.frtAssigned && !!g.frtStage) &&
      (scoped !== null || frtScope !== null || (!g.feAssigned && !g.frtAssigned)) && !(frtScope && g.frtStage === "FE_VERIFIED");
    const fullEdit = rowEdit && !(scoped !== null && g.frtAssigned); // GP code / name / block correction (FE: own GPs only)
    const textEdit = rowEdit;
    const catOptions: GpCategory[] | undefined = frtScope ? ["A", "C", "D"] : undefined;
    const catChanged = !!d?.category && d.category !== (g.gpCategory ?? null);
    const needsEvidence =
      rowEdit && !!d && (catChanged || g.review === "RETURNED" || (!!frtScope && g.frtStage === "RETURNED_FRT")) &&
      ((d.remark ?? "").trim().length < MIN_REMARK || !d.files.some(camOnly ? isCameraPhoto : isPhoto));
    return { d, done, cat, cum, rowEdit, fullEdit, textEdit, catOptions, needsEvidence, pickable: reviewable(g, roles) };
  };

  /** Proof of a GP: saved files, the files waiting for the next submission and – when the GP can be changed – the
   * Camera (FRT: live photo with location) and Attach buttons. */
  const proofCell = (g: TicketTaskGp, x: ReturnType<typeof info>) => (
    <>
      {g.files.length > 0 && <ProofList files={g.files} compact />}
      {x.d?.files.map((f, i) => {
        const geo = (f as GeoFile).geo;
        return (
          <span key={`${f.name}-${i}`} className="mt-0.5 flex items-center gap-1 text-[0.75rem] text-[var(--series-7)]">
            {geo ? <Camera className="size-3.5 shrink-0" aria-hidden /> : <Paperclip className="size-3.5 shrink-0" aria-hidden />}
            <span className="min-w-0 flex-1 truncate" title={`${f.name} (${fileSize(f.size)}) – sent with the next submission`}>
              {f.name}
              {geo && (
                <span className="block text-[0.6875rem] text-good-text">
                  <MapPin className="mr-0.5 inline size-3" aria-hidden />
                  {geo.lat.toFixed(5)}, {geo.lng.toFixed(5)}
                </span>
              )}
            </span>
            <button type="button" disabled={busy} onClick={() => set(g.id, { files: x.d!.files.filter((_, j) => j !== i) })} className="rounded p-0.5 hover:bg-accent" aria-label={`Remove ${f.name}`}>
              <X className="size-3" />
            </button>
          </span>
        );
      })}
      {x.needsEvidence && <span className="block text-[0.6875rem] font-medium text-critical-text">{camOnly ? CAMERA_HINT : EVIDENCE_HINT}</span>}
      {x.textEdit ? (
        <span className="mt-0.5 flex flex-wrap items-center gap-1">
          {camOnly && (
            <button
              type="button"
              disabled={busy}
              onClick={() => setCamFor(g)}
              className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-[0.75rem] font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              title="Take a live photo – its location (latitude / longitude), date and time are saved with it"
            >
              <Camera className="size-3.5" aria-hidden /> Camera
            </button>
          )}
          <label className={cn("inline-flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 text-[0.75rem] font-medium text-primary hover:bg-primary-soft", busy && "pointer-events-none opacity-50")}>
            <Paperclip className="size-3.5" aria-hidden /> {camOnly ? "Attach document" : frtScope ? "Upload photo" : "Attach"}
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
        </span>
      ) : (
        g.files.length === 0 && <span className="text-[0.75rem] text-muted-foreground">Proof Not Uploaded</span>
      )}
    </>
  );

  /** The FE's Verify / Return of the FRT's Daily Achievement (shown while nothing is being changed). */
  const checkButtons = (g: TicketTaskGp, x: ReturnType<typeof info>) =>
    (canVerify(g) || canReturnFrt(g)) && !x.d ? (
      <span className="flex flex-wrap items-center gap-1">
        {canVerify(g) && (
          <button
            type="button"
            onClick={() => setChecking({ g, action: "FE_VERIFY" })}
            className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-good px-2 py-1 text-[0.71875rem] font-semibold text-white hover:bg-good/90"
            title="The FRT's proof and remark are correct – send the GP to the Area Manager"
          >
            <CheckCircle2 className="size-3.5" aria-hidden /> Verify → AM
          </button>
        )}
        <button
          type="button"
          onClick={() => setChecking({ g, action: "FE_RETURN" })}
          className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-critical/40 px-2 py-1 text-[0.71875rem] font-semibold text-critical-text hover:bg-critical-soft"
          title="Send the GP back to the FRT with the reason"
        >
          <Undo2 className="size-3.5" aria-hidden /> Return to FRT
        </button>
      </span>
    ) : null;

  const T = task.totals;
  return (
    <Card className={cn("p-0", frtScope || feView || amView ? "overflow-clip" : "overflow-hidden")}>
      {/* header: who / which week, downloads */}
      <div className="flex flex-col gap-3 border-b border-border px-5 py-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-base font-bold text-subheading">
            <ListChecks className="size-4 text-primary" aria-hidden /> GP-wise Weekly Task
            {(scoped || frtScope) && <span className="rounded-full bg-primary-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-primary">Your GPs only</span>}
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
            {frtScope && (
              <>
                FRT <b className="font-semibold text-foreground">{frtScope.frtCode ?? "—"}</b> ({frtScope.frtName})
                {frtScope.fes.length > 0 && <> · FE {frtScope.fes.join(", ")}</>} · Area Manager{" "}
              </>
            )}
            {smeView && <>Ticket {t.code} · Area Manager </>}
            <b className="font-semibold text-foreground">{task.areaManager}</b>
            {task.gpSource === "NO_AM" && <> (acting AM – GPs without an Area Manager in the Escalation Matrix)</>}
            {task.gpSource === "AM+NO_AM" && <> (with the GPs without an Area Manager)</>}
            {task.circle && <> · {task.circle}</>}
            {task.cbhName && <> · CBH {task.cbhName}</>} · {task.week.id.replace("W-", "Week ")} ({dm(task.week.start)} – {dm(task.week.end)}) · targets from {task.sourceFile}, data as of {ticketDay(task.dataAsOf)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <a href={ticketApi.taskWorkbookUrl(t.id, "assignment")} download>
              <FileSpreadsheet /> {scoped || frtScope || smeView ? "My Assignment Excel" : "Assignment Excel"}
            </a>
          </Button>
          <Button asChild size="sm" variant="outline">
            <a href={ticketApi.taskWorkbookUrl(t.id, "progress")} download>
              <Download /> {scoped || frtScope || smeView ? "My latest Excel" : "Download latest Excel"}
            </a>
          </Button>
        </div>
      </div>

      {/* SME / COH: the ticket's GPs against the GPs handed to them */}
      {kpis && reviewer && (
        <div className={cn("grid grid-cols-2 gap-3 border-b border-border px-5 py-3 sm:grid-cols-3", reviewer === "COH" ? "lg:grid-cols-8" : "lg:grid-cols-7")}>
          <Stat label="Total GPs in Ticket" value={kpis.ticketGps} sub="all GPs of the Area Manager's ticket" />
          <Stat label="Assigned to You" value={kpis.assigned} cls="text-[var(--series-1)]" sub={reviewer === "SME" ? "approved & forwarded by the AM" : "reviewed & forwarded by the SME"} />
          <Stat label={reviewer === "SME" ? "Pending Your Review" : "Pending Letter Submission"} value={kpis.pending} cls={kpis.pending ? "text-warning-text" : undefined}
            sub={reviewer === "SME" && kpis.returnedToYou ? `${kpis.returnedToYou} sent back by the COH` : undefined} />
          {reviewer === "SME" ? (
            <>
              <Stat label="Forwarded to COH" value={kpis.forwarded ?? 0} cls="text-good-text" />
              <Stat label="Returned by COH" value={kpis.returnedToYou ?? 0} cls={kpis.returnedToYou ? "text-critical-text" : undefined} sub="review these again" />
            </>
          ) : (
            <>
              <Stat label="Letter Submitted" value={kpis.letterSubmitted ?? 0} cls="text-good-text" />
              <Stat
                label="AMC Pending"
                value={task.gps.filter((g) => g.review === "LETTER_SUBMITTED").length}
                cls={task.gps.some((g) => g.review === "LETTER_SUBMITTED") ? "text-warning-text" : undefined}
                sub="letter done – record the AMC"
              />
              <Stat label="AMC Converted" value={kpis.amcConverted ?? 0} cls="text-good-text" />
            </>
          )}
          <Stat label="Non-Doable Pending" value={ndWaiting} cls={ndWaiting ? "text-critical-text" : undefined} sub="open the case to review" />
          <Stat label={reviewer === "SME" ? "Sent Back to AM" : "Sent Back to SME"} value={kpis.sentBack} cls={kpis.sentBack ? "text-critical-text" : undefined} />
        </div>
      )}

      {/* FRT: their GPs and where they are */}
      {frtScope && <FrtSummary gps={task.gps} />}
      {/* FE: what waits for them */}
      {feView && <FeSummary gps={task.gps} />}
      {/* Area Manager: what waits for them and the team */}
      {amView && <AmSummary gps={task.gps} achieved={task.totals.achieved} target={task.totals.target} />}

      {/* totals + progress */}
      {!(kpis && reviewer) && !frtScope && (
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

      {/* Area Manager / admin: FE-wise allocation and progress */}
      {showFe &&
        (amView ? (
          <details className="border-b border-border">
            <summary className="cursor-pointer px-5 py-2.5 text-[0.8125rem] font-semibold text-primary">Field Engineer-wise summary ({fes.length})</summary>
            <FeSplit fes={fes} />
          </details>
        ) : (
          <FeSplit fes={fes} />
        ))}
      {/* FRT-wise target and progress (Area Manager / admin: every FRT; FE: the FRTs of their GPs) */}
      {frts.length > 0 &&
        !frtScope &&
        !smeView &&
        (amView ? (
          <details className="border-b border-border">
            <summary className="cursor-pointer px-5 py-2.5 text-[0.8125rem] font-semibold text-primary">FRT-wise summary ({frts.length})</summary>
            <FrtSplit frts={frts} />
          </details>
        ) : (
          <FrtSplit frts={frts} />
        ))}

      {/* FRT: what happens to their Daily Achievement */}
      {frtScope && editable && <FrtSteps fes={frtScope.fes} camera={camOnly} />}

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
        {amView ? (
          <Input value={amSearch} onChange={(e) => setAmSearch(e.target.value)} placeholder="Search GP code, name, block, FRT…" className="h-9 w-72 text-[0.8125rem]" aria-label="Search GPs" />
        ) : (
          <Select
            ariaLabel="Review stage"
            value={stage}
            onValueChange={(v) => v && setStage(v)}
            options={[{ value: ALL_STAGES, label: "All review stages" }, ...Object.entries(REVIEW_STAGE).map(([k, v]) => ({ value: k, label: v.label }))]}
            className="w-52"
          />
        )}
        <span className="text-muted-foreground">
          {amView ? amShown.length : shown.length} of {task.gps.length} GPs
        </span>
      </div>
      )}

      {ndPending.length > 0 && t.status !== "CLOSED" && (
        <div role="alert" className="border-b-2 border-critical bg-critical-soft px-5 py-3">
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-start gap-2.5">
              <OctagonAlert className="mt-0.5 size-5 shrink-0 text-critical-text" aria-hidden />
              <div className="text-[0.8125rem] text-critical-text">
                <p className="text-sm font-bold">
                  Non-Doable case{ndPending.length === 1 ? "" : "s"} waiting for you – Daily Achievement is locked
                </p>
                <p>
                  Open {ndPending.length === 1 ? "the case" : "each case"} and submit the <b>E1 Physical Verification</b> and the <b>E2 Justification</b>. After that you can submit the
                  Daily Achievement again.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {ndPending.map((c) => (
                <Button key={c.caseId} asChild size="sm" variant="primary" className="bg-critical hover:bg-critical/90">
                  <Link href={`/dashboard/tickets/non-doable?case=${c.caseId}`} title={c.label}>
                    <OctagonAlert /> Open {c.ref} · GP {c.gpCode}
                  </Link>
                </Button>
              ))}
            </div>
          </div>
        </div>
      )}

      {roles.length > 0 && t.status !== "CLOSED" && <ReviewBar t={t} roles={roles} selected={selected} onClear={() => setPicked(new Set())} onChanged={onChanged} />}

      {/* FRT: optional E1 / E2 of its Non-Doable cases in a popup (after the submission or from the GP row) */}
      {frtScope && (
        <NdFillDialog
          caseIds={ndFill?.ids ?? null}
          justSubmitted={!!ndFill?.just}
          onClose={() => setNdFill(null)}
          onChanged={() =>
            ticketApi
              .get(t.id)
              .then((next) => onChanged(next, null))
              .catch(() => undefined)
          }
        />
      )}

      {/* Non-Doable cases of this ticket waiting for the user (e.g. COH: Forward → Corporate Team – MGG), same actions as Non-Doable Cases */}
      {!admin && t.status !== "CLOSED" && (
        <TicketNdCases
          ticketId={t.id}
          version={task.gps.filter((g) => g.ndCase?.open).map((g) => `${g.ndCase!.id}:${g.ndCase!.status}`).join(",")}
          onStep={() =>
            ticketApi
              .get(t.id)
              .then((next) => onChanged(next, null))
              .catch(() => undefined)
          }
        />
      )}

      {/* SME: only the GPs forwarded to them, FE submission and AM approval side by side */}
      {/* SME / COH: work tabs, the proofs and the row's own step (SmeReviewTable / CohReviewTable) */}
      {reviewer === "SME" && <SmeReviewTable t={t} ndCases={ndCases} roles={roles} picked={picked} setPicked={setPicked} onChanged={onChanged} />}
      {reviewer === "COH" && <CohReviewTable t={t} ndCases={ndCases} roles={roles} picked={picked} setPicked={setPicked} onChanged={onChanged} />}

      {/* FRT: GP | Daily Achievement | Remark | Proof | FE Check (same rules as the full table) */}
      {frtScope && (
        <div className="hidden max-h-[35rem] overflow-auto md:block">
          <table className="w-full min-w-[68rem] text-[0.8125rem]">
            <caption className="sr-only">Your GPs – Daily Achievement</caption>
            <thead className="sticky top-0 z-10">
              <tr className="border-b border-border bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                {["GP Code", "GP Name", "Block", "Daily Achievement", "Remark", "Proof", "FE Check"].map((h) => (
                  <th key={h} scope="col" className="px-3 py-2">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((g) => {
                const x = info(g);
                // left stripe: green = remark + photo ready, amber = something missing, none = not changed
                const stripe = x.d ? (x.needsEvidence ? "border-l-warning" : "border-l-good") : "border-l-transparent";
                return (
                  <tr key={g.id} className={cn("border-b border-border/70 align-top transition-colors last:border-0 hover:bg-muted/40", x.d && "bg-primary-soft/20", g.frtStage === "RETURNED_FRT" && !x.d && "bg-critical-soft/20")}>
                    <td className={cn("w-[9.5rem] border-l-4 px-2 py-2", stripe)}>
                      {x.fullEdit ? (
                        <Input
                          value={x.d?.gpCode ?? g.gpCode}
                          maxLength={40}
                          disabled={busy}
                          onChange={(e) => set(g.id, { gpCode: e.target.value })}
                          aria-invalid={x.d?.gpCode !== undefined && !GP_CODE.test(x.d.gpCode.trim())}
                          className={cn("h-9 text-[0.8125rem] font-semibold", x.d?.gpCode !== undefined && !GP_CODE.test(x.d.gpCode.trim()) && "border-critical")}
                          aria-label={`GP code of ${g.gpCode}`}
                        />
                      ) : (
                        <span className="font-semibold">{g.gpCode}</span>
                      )}
                      <GpTicketId t={t} gpId={g.id} />
                      <span className="mt-0.5 flex items-center gap-1.5">
                        <button type="button" onClick={() => setDetailId(g.id)} className="text-[0.6875rem] font-medium text-primary hover:underline" title="Open the GP details and history">
                          Details
                        </button>
                        {g.kind === "ADDED" && <span className="rounded bg-muted px-1.5 py-0.5 text-[0.625rem] font-semibold">Added</span>}
                      </span>
                    </td>
                    <td className="w-[11rem] px-2 py-2">
                      {x.fullEdit ? (
                        <Input value={x.d?.gpName ?? g.gpName} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { gpName: e.target.value })} className="h-9 text-[0.8125rem]" aria-label={`GP name of ${g.gpCode}`} />
                      ) : (
                        g.gpName
                      )}
                    </td>
                    <td className="w-[9rem] px-2 py-2">
                      {x.fullEdit ? (
                        <Input value={x.d?.block ?? g.block ?? ""} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { block: e.target.value })} placeholder="Block" className="h-9 text-[0.8125rem]" aria-label={`Block of ${g.gpCode}`} />
                      ) : (
                        <span className="text-muted-foreground">{g.block ?? "—"}</span>
                      )}
                    </td>
                    <td className="w-[12rem] px-2 py-2">
                      {x.rowEdit ? (
                        <GpCategorySelect value={x.cat} disabled={busy} options={x.catOptions} onChange={(v) => set(g.id, { category: v === (g.gpCategory ?? null) ? null : v })} ariaLabel={`Daily achievement of ${g.gpCode}`} />
                      ) : (
                        <GpCategoryBadge code={x.cat} />
                      )}
                      {x.rowEdit && x.d && (
                        <button
                          type="button"
                          className="mt-1 text-[0.71875rem] font-medium text-muted-foreground hover:text-primary disabled:opacity-50"
                          disabled={busy}
                          onClick={() => setDraft((cur) => Object.fromEntries(Object.entries(cur).filter(([k]) => Number(k) !== g.id)))}
                          title="Undo the unsubmitted change of this GP"
                        >
                          Clear change
                        </button>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {x.textEdit ? (
                        <Input value={x.d?.remark ?? g.remarks ?? ""} maxLength={500} disabled={busy} onChange={(e) => set(g.id, { remark: e.target.value })} placeholder="Remark" className="h-9 text-[0.8125rem]" aria-label={`Remark for ${g.gpCode}`} />
                      ) : (
                        <span className="text-[0.8125rem]">{g.remarks ?? <span className="text-muted-foreground">—</span>}</span>
                      )}
                    </td>
                    <td className="w-[12rem] px-2 py-2">
                      <span className="flex flex-wrap items-center gap-2">
                        <FrtProofChips saved={g.files} draft={x.d?.files ?? []} disabled={busy} onRemove={(i) => set(g.id, { files: (x.d?.files ?? []).filter((_, j) => j !== i) })} />
                        {x.textEdit && (
                          <>
                            {camOnly && (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => setCamFor(g)}
                                className="flex size-10 items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                                title="Take a live photo – its location, date and time are saved with it"
                                aria-label={`Camera photo for ${g.gpCode}`}
                              >
                                <Camera className="size-4" />
                              </button>
                            )}
                            <label
                              className={cn("flex size-10 cursor-pointer items-center justify-center rounded-md border border-dashed border-primary/50 text-primary hover:bg-primary-soft", busy && "pointer-events-none opacity-50")}
                              title={camOnly ? "Attach a document" : "Upload a photo (JPG / PNG)"}
                            >
                              {camOnly ? <Paperclip className="size-4" aria-hidden /> : <Plus className="size-4" aria-hidden />}
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
                                aria-label={`${camOnly ? "Attach a document" : "Upload a photo"} for ${g.gpCode}`}
                              />
                            </label>
                          </>
                        )}
                        {!x.textEdit && g.files.length === 0 && <span className="text-[0.75rem] text-muted-foreground">No proof</span>}
                      </span>
                      {x.needsEvidence && <span className="mt-1 block text-[0.6875rem] font-medium text-warning-text">{camOnly ? CAMERA_HINT : EVIDENCE_HINT}</span>}
                    </td>
                    <td className="w-[9.5rem] px-2 py-2.5">
                      <FrtCheckBadge g={g} onOpenNd={(id) => setNdFill({ ids: [id], just: false })} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* FE: two parts – the FRT's reports to verify, and the FE's own GPs (no FRT login) to fill */}
      {feView && (
        <div className="hidden md:block">
          <div role="tablist" aria-label="Your GPs" className="flex flex-wrap items-end gap-1 border-b border-border px-5 pt-2">
            {(
              [
                ["verify", "FRT GPs – verify / fill", feFrt.length, feFrt.filter((g) => g.frtStage === "PENDING_FE" || (!g.frtStage && !g.gpCategory)).length],
                ["own", "Your GPs – fill yourself", feOwn.length, feOwn.filter((g) => !g.gpCategory || g.review === "RETURNED").length],
              ] as const
            ).map(([key, label, total, todo]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                onClick={() => setFeTab(key)}
                className={cn(
                  "-mb-px inline-flex items-center gap-2 rounded-t-md border-b-2 px-3 py-2 text-[0.8125rem] font-semibold",
                  tab === key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {label} <span className="rounded-full bg-muted px-1.5 text-[0.6875rem] text-foreground">{total}</span>
                {todo > 0 && <span className="rounded-full bg-warning-soft px-1.5 text-[0.6875rem] text-warning-text" title="Need your action">{todo} to do</span>}
              </button>
            ))}
            {editable && (
              <Button
                size="sm"
                variant="outline"
                className="mb-1.5 ml-auto"
                disabled={busy || rows.length >= 50}
                onClick={() => {
                  setRows((cur) => [...cur, { key: Date.now() + cur.length, gpCode: "", gpName: "", block: "", category: null, remark: "", files: [] }]);
                  setTimeout(() => document.getElementById("add-gps")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
                }}
              >
                <Plus /> Add GP
              </Button>
            )}
          </div>

          {/* several FRT reports at once: one remark for all */}
          {tab === "verify" && feSelected.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-b border-border bg-primary-soft/40 px-5 py-2 text-[0.8125rem]">
              <b>{feSelected.length} GP{feSelected.length === 1 ? "" : "s"} selected</b>
              <button
                type="button"
                onClick={() => setChecking({ g: feSelected[0], action: "FE_VERIFY", all: feSelected })}
                className="inline-flex items-center gap-1 rounded-md bg-good px-2.5 py-1 text-[0.75rem] font-semibold text-white hover:bg-good/90"
              >
                <CheckCircle2 className="size-3.5" aria-hidden /> Verify → AM
              </button>
              <button
                type="button"
                onClick={() => setChecking({ g: feSelected[0], action: "FE_RETURN", all: feSelected })}
                className="inline-flex items-center gap-1 rounded-md border border-critical/40 px-2.5 py-1 text-[0.75rem] font-semibold text-critical-text hover:bg-critical-soft"
              >
                <Undo2 className="size-3.5" aria-hidden /> Return to FRT
              </button>
              <button type="button" onClick={() => setFeSel(new Set())} className="text-[0.75rem] font-medium text-muted-foreground hover:text-primary">
                Clear selection
              </button>
            </div>
          )}

          <div className="max-h-[35rem] overflow-auto">
            {tab === "verify" ? (
              <table className="w-full min-w-[72rem] text-[0.8125rem]">
                <caption className="sr-only">FRT reports to verify</caption>
                <thead className="sticky top-0 z-10">
                  <tr className="border-b border-border bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                    <th scope="col" className="w-8 px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label="Select all GPs waiting for your verification"
                        disabled={feVerifiable.length === 0}
                        checked={feVerifiable.length > 0 && feVerifiable.every((g) => feSel.has(g.id))}
                        onChange={(e) => setFeSel(e.target.checked ? new Set(feVerifiable.map((g) => g.id)) : new Set())}
                        className="size-4 accent-[var(--primary)]"
                      />
                    </th>
                    {["GP Code", "GP Name", "Block", "FRT", "T · A · G", "Status", "Remark", "Proof", "Action"].map((h) => (
                      <th key={h} scope="col" className={cn("px-2 py-2", h === "GP Code" && "sticky left-0 z-20 bg-muted")} title={h === "T · A · G" ? "Target · Achieved · Gap" : undefined}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {feRows.length === 0 && (
                    <tr>
                      <td colSpan={10} className="px-5 py-6 text-center text-muted-foreground">
                        No FRT GPs here.
                      </td>
                    </tr>
                  )}
                  {feRows.map((g) => {
                    const x = info(g);
                    const stripe = x.d
                      ? x.needsEvidence ? "border-l-warning" : "border-l-good"
                      : g.frtStage === "PENDING_FE" && canVerify(g) ? "border-l-warning" : g.review === "RETURNED" ? "border-l-critical" : "border-l-transparent";
                    return (
                      <tr key={g.id} className="border-b border-border/70 align-top transition-colors last:border-0 hover:bg-muted/40">
                        <td className={cn("border-l-4 px-3 py-2.5", stripe)}>
                          <input
                            type="checkbox"
                            aria-label={`Select ${g.gpCode}`}
                            disabled={!canVerify(g)}
                            checked={feSel.has(g.id)}
                            onChange={(e) =>
                              setFeSel((cur) => {
                                const next = new Set(cur);
                                if (e.target.checked) next.add(g.id);
                                else next.delete(g.id);
                                return next;
                              })
                            }
                            className="size-4 accent-[var(--primary)] disabled:opacity-30"
                          />
                        </td>
                        <td className="sticky left-0 z-[5] bg-card px-2 py-2.5">
                          <button type="button" onClick={() => setDetailId(g.id)} className="font-semibold text-primary hover:underline" title="Open the GP details and history">
                            {g.gpCode}
                          </button>
                          <GpTicketId t={t} gpId={g.id} />
                          <span className="mt-0.5 block">
                            <TypeTag g={g} />
                          </span>
                        </td>
                        <td className="px-2 py-2.5">{g.gpName}</td>
                        <td className="px-2 py-2.5 text-muted-foreground">{g.block ?? "—"}</td>
                        <td className="whitespace-nowrap px-2 py-2.5 font-medium">{g.frtCode ?? "—"}</td>
                        <td className="px-2 py-2.5">
                          <TagCell target={g.target} achieved={x.cum} />
                        </td>
                        <td className="w-[12rem] space-y-1 px-2 py-2">
                          {x.rowEdit ? (
                            <>
                              <GpCategorySelect value={x.cat} disabled={busy} options={x.catOptions} onChange={(v) => set(g.id, { category: v === (g.gpCategory ?? null) ? null : v })} ariaLabel={`Daily achievement of ${g.gpCode}`} />
                              {x.d && (
                                <button
                                  type="button"
                                  className="text-[0.71875rem] font-medium text-muted-foreground hover:text-primary disabled:opacity-50"
                                  disabled={busy}
                                  onClick={() => setDraft((cur) => Object.fromEntries(Object.entries(cur).filter(([k]) => Number(k) !== g.id)))}
                                  title="Undo the unsubmitted change of this GP"
                                >
                                  Clear change
                                </button>
                              )}
                            </>
                          ) : (
                            <>
                              {x.cat || !x.done ? <GpCategoryBadge code={x.cat} /> : <GpStatusBadge status={g.status} />}
                              <ReviewCell g={g} onTimeline={smeView ? undefined : () => setDetailId(g.id)} />
                            </>
                          )}
                        </td>
                        <td className="min-w-[12rem] max-w-[16rem] px-2 py-2">
                          {x.textEdit ? (
                            <Input value={x.d?.remark ?? g.remarks ?? ""} maxLength={500} disabled={busy} onChange={(e) => set(g.id, { remark: e.target.value })} placeholder="Remark" className="h-9 text-[0.8125rem]" aria-label={`Remark for ${g.gpCode}`} />
                          ) : (
                            <span className="line-clamp-2" title={g.remarks ?? undefined}>
                              {g.remarks ?? <span className="text-muted-foreground">—</span>}
                            </span>
                          )}
                        </td>
                        <td className="w-[11rem] px-2 py-2">
                          <span className="flex flex-wrap items-center gap-2">
                            <FrtProofChips saved={g.files} draft={x.d?.files ?? []} disabled={busy} onRemove={(i) => set(g.id, { files: (x.d?.files ?? []).filter((_, j) => j !== i) })} />
                            {x.textEdit && camOnly && (
                              // FE on a phone: a live Camera photo (location / date / time) – same as the FRT
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => setCamFor(g)}
                                className="flex size-10 items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                                title="Take a live photo – its location, date and time are saved with it"
                                aria-label={`Camera photo for ${g.gpCode}`}
                              >
                                <Camera className="size-4" />
                              </button>
                            )}
                            {x.textEdit && (
                              <label
                                className={cn("flex size-10 cursor-pointer items-center justify-center rounded-md border border-dashed border-primary/50 text-primary hover:bg-primary-soft", busy && "pointer-events-none opacity-50")}
                                title={camOnly ? "Attach a document" : "Upload a photo (JPG / PNG) or a document"}
                              >
                                {camOnly ? <Paperclip className="size-4" aria-hidden /> : <Plus className="size-4" aria-hidden />}
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
                                  aria-label={`${camOnly ? "Attach a document" : "Upload proof"} for ${g.gpCode}`}
                                />
                              </label>
                            )}
                            {!x.textEdit && g.files.length === 0 && <span className="text-[0.75rem] text-muted-foreground">No proof</span>}
                          </span>
                          {x.needsEvidence && <span className="mt-1 block text-[0.6875rem] font-medium text-warning-text">{camOnly ? CAMERA_HINT : EVIDENCE_HINT}</span>}
                        </td>
                        <td className="px-2 py-2">
                          {checkButtons(g, x) ??
                            (x.rowEdit ? (
                              <span className="block max-w-[10rem] text-[0.6875rem] text-muted-foreground">FRT has not reported – fill it and submit, it goes to the Area Manager</span>
                            ) : (
                              <span className="text-[0.75rem] text-muted-foreground">—</span>
                            ))}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <table className="w-full min-w-[76rem] text-[0.8125rem]">
                <caption className="sr-only">Your GPs – Daily Achievement</caption>
                <thead className="sticky top-0 z-10">
                  <tr className="border-b border-border bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                    {["GP Code", "GP Name", "Block", "T · A · G", "Daily Achievement", "Remark", "Proof", "AM Review"].map((h) => (
                      <th key={h} scope="col" className={cn("px-2 py-2", h === "GP Code" && "sticky left-0 z-20 bg-muted")} title={h === "T · A · G" ? "Target · Achieved · Gap" : undefined}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {feRows.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-5 py-6 text-center text-muted-foreground">
                        No GPs without an FRT login – your FRTs report all your GPs.
                      </td>
                    </tr>
                  )}
                  {feRows.map((g) => {
                    const x = info(g);
                    const badEdit = x.d?.gpCode !== undefined && !GP_CODE.test(x.d.gpCode.trim());
                    const stripe = x.d ? (x.needsEvidence ? "border-l-warning" : "border-l-good") : g.review === "RETURNED" ? "border-l-critical" : "border-l-transparent";
                    return (
                      <tr key={g.id} className={cn("border-b border-border/70 align-top transition-colors last:border-0 hover:bg-muted/40", x.d && "bg-primary-soft/20", g.review === "RETURNED" && !x.d && "bg-critical-soft/20")}>
                        <td className={cn("sticky left-0 z-[5] bg-card w-[9.5rem] border-l-4 px-2 py-2", stripe)}>
                          {x.fullEdit ? (
                            <Input
                              value={x.d?.gpCode ?? g.gpCode}
                              maxLength={40}
                              disabled={busy}
                              onChange={(e) => set(g.id, { gpCode: e.target.value })}
                              aria-invalid={badEdit}
                              className={cn("h-9 text-[0.8125rem] font-semibold", badEdit && "border-critical")}
                              aria-label={`GP code of ${g.gpCode}`}
                            />
                          ) : (
                            <span className="font-semibold">{g.gpCode}</span>
                          )}
                          <GpTicketId t={t} gpId={g.id} />
                          <span className="mt-0.5 flex items-center gap-1.5">
                            <button type="button" onClick={() => setDetailId(g.id)} className="text-[0.6875rem] font-medium text-primary hover:underline" title="Open the GP details and history">
                              Details
                            </button>
                            <TypeTag g={g} />
                          </span>
                        </td>
                        <td className="w-[11rem] px-2 py-2">
                          {x.fullEdit ? (
                            <Input value={x.d?.gpName ?? g.gpName} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { gpName: e.target.value })} className="h-9 text-[0.8125rem]" aria-label={`GP name of ${g.gpCode}`} />
                          ) : (
                            g.gpName
                          )}
                        </td>
                        <td className="w-[9rem] px-2 py-2">
                          {x.fullEdit ? (
                            <Input value={x.d?.block ?? g.block ?? ""} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { block: e.target.value })} placeholder="Block" className="h-9 text-[0.8125rem]" aria-label={`Block of ${g.gpCode}`} />
                          ) : (
                            <span className="text-muted-foreground">{g.block ?? "—"}</span>
                          )}
                        </td>
                        <td className="px-2 py-2.5">
                          <TagCell target={g.target} achieved={x.cum} />
                        </td>
                        <td className="w-[12rem] px-2 py-2">
                          {x.rowEdit ? (
                            <GpCategorySelect value={x.cat} disabled={busy} options={x.catOptions} onChange={(v) => set(g.id, { category: v === (g.gpCategory ?? null) ? null : v })} ariaLabel={`Daily achievement of ${g.gpCode}`} />
                          ) : x.cat || !x.done ? (
                            <GpCategoryBadge code={x.cat} />
                          ) : (
                            <GpStatusBadge status={g.status} />
                          )}
                          {x.rowEdit && x.d && (
                            <button
                              type="button"
                              className="mt-1 text-[0.71875rem] font-medium text-muted-foreground hover:text-primary disabled:opacity-50"
                              disabled={busy}
                              onClick={() => setDraft((cur) => Object.fromEntries(Object.entries(cur).filter(([k]) => Number(k) !== g.id)))}
                              title="Undo the unsubmitted change of this GP"
                            >
                              Clear change
                            </button>
                          )}
                        </td>
                        <td className="min-w-[13rem] px-2 py-2">
                          {x.textEdit ? (
                            <Input value={x.d?.remark ?? g.remarks ?? ""} maxLength={500} disabled={busy} onChange={(e) => set(g.id, { remark: e.target.value })} placeholder="Remark" className="h-9 text-[0.8125rem]" aria-label={`Remark for ${g.gpCode}`} />
                          ) : (
                            <span className="text-[0.8125rem]">{g.remarks ?? <span className="text-muted-foreground">—</span>}</span>
                          )}
                        </td>
                        <td className="w-[12rem] px-2 py-2">
                          <span className="flex flex-wrap items-center gap-2">
                            <FrtProofChips saved={g.files} draft={x.d?.files ?? []} disabled={busy} onRemove={(i) => set(g.id, { files: (x.d?.files ?? []).filter((_, j) => j !== i) })} />
                            {x.textEdit && camOnly && (
                              // FE on a phone: a live Camera photo (location / date / time) – same as the FRT
                              <button
                                type="button"
                                disabled={busy}
                                onClick={() => setCamFor(g)}
                                className="flex size-10 items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                                title="Take a live photo – its location, date and time are saved with it"
                                aria-label={`Camera photo for ${g.gpCode}`}
                              >
                                <Camera className="size-4" />
                              </button>
                            )}
                            {x.textEdit && (
                              <label
                                className={cn("flex size-10 cursor-pointer items-center justify-center rounded-md border border-dashed border-primary/50 text-primary hover:bg-primary-soft", busy && "pointer-events-none opacity-50")}
                                title={camOnly ? "Attach a document" : "Upload a photo (JPG / PNG) or a document"}
                              >
                                {camOnly ? <Paperclip className="size-4" aria-hidden /> : <Plus className="size-4" aria-hidden />}
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
                                  aria-label={`${camOnly ? "Attach a document" : "Upload proof"} for ${g.gpCode}`}
                                />
                              </label>
                            )}
                            {!x.textEdit && g.files.length === 0 && <span className="text-[0.75rem] text-muted-foreground">No proof</span>}
                          </span>
                          {x.needsEvidence && <span className="mt-1 block text-[0.6875rem] font-medium text-warning-text">{camOnly ? CAMERA_HINT : EVIDENCE_HINT}</span>}
                        </td>
                        <td className="w-[9rem] px-2 py-2.5">
                          <ReviewCell g={g} onTimeline={smeView ? undefined : () => setDetailId(g.id)} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* Area Manager: work tabs (approval pending first), one row per GP with its proof and Approve / Return */}
      {amView && (
        <div className="hidden md:block">
          <div role="tablist" aria-label="GPs by stage" className="flex flex-wrap items-end gap-1 border-b border-border px-5 pt-2">
            {AM_TABS.map((tb) => (
              <button
                key={tb.key}
                type="button"
                role="tab"
                aria-selected={amTabNow === tb.key}
                title={tb.hint}
                onClick={() => {
                  setAmTab(tb.key);
                  setPicked(new Set());
                }}
                className={cn(
                  "-mb-px inline-flex items-center gap-2 rounded-t-md border-b-2 px-3 py-2 text-[0.8125rem] font-semibold",
                  amTabNow === tb.key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {tb.label}
                <span className={cn("rounded-full px-1.5 text-[0.6875rem]", tb.key === "pending" && amCount("pending") ? "bg-warning-soft text-warning-text" : "bg-muted text-foreground")}>{amCount(tb.key)}</span>
              </button>
            ))}
          </div>
          <div className="max-h-[35rem] overflow-auto">
            <table className="w-full min-w-[74rem] text-[0.8125rem]">
              <caption className="sr-only">GPs of the ticket – Area Manager review</caption>
              <thead className="sticky top-0 z-10">
                <tr className="border-b border-border bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="w-8 px-3 py-2">
                    {roles.length > 0 && (
                      <input
                        type="checkbox"
                        aria-label="Select all GPs that can be reviewed"
                        disabled={amPickable.length === 0}
                        checked={amPickable.length > 0 && amPickable.every((g) => picked.has(g.id))}
                        onChange={(e) => setPicked(e.target.checked ? new Set(amPickable.map((g) => g.id)) : new Set())}
                        className="size-4 accent-[var(--primary)]"
                      />
                    )}
                  </th>
                  {["GP Code", "GP Name · Block", "FE / FRT", "T · A · G", "Daily Achievement", "Remark", "Proof", "Action", "Stage"].map((h) => (
                    <th key={h} scope="col" className={cn("px-2 py-2", h === "GP Code" && "sticky left-0 z-20 bg-muted")} title={h === "T · A · G" ? "Target · Achieved · Gap" : undefined}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {amRows.length === 0 && (
                  <tr>
                    <td colSpan={10} className="px-5 py-6 text-center text-muted-foreground">
                      {amTabNow === "pending" ? "Nothing waiting for your approval." : "No GPs here."}
                    </td>
                  </tr>
                )}
                {amRows.map((g) => {
                  const x = info(g);
                  const bucket = amBucket(g);
                  const stripe = x.d
                    ? x.needsEvidence ? "border-l-warning" : "border-l-good"
                    : bucket === "pending" ? "border-l-warning" : bucket === "returned" ? "border-l-critical" : bucket === "approved" ? "border-l-good" : "border-l-transparent";
                  const sub = g.feSubmission;
                  const canAct = roles.includes("AM") && t.status !== "CLOSED" && !x.d;
                  return (
                    <tr key={g.id} className={cn("border-b border-border/70 align-top transition-colors last:border-0 hover:bg-muted/40", x.d && "bg-primary-soft/20")}>
                      <td className={cn("border-l-4 px-3 py-2.5", stripe)}>
                        {roles.length > 0 && (
                          <input
                            type="checkbox"
                            aria-label={`Select ${g.gpCode} for review`}
                            disabled={!x.pickable}
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
                        )}
                      </td>
                      <td className="sticky left-0 z-[5] bg-card px-2 py-2.5">
                        <button type="button" onClick={() => setDetailId(g.id)} className="font-semibold text-primary hover:underline" title="Open the GP details (FE submission, AM approval, review history)">
                          {g.gpCode}
                        </button>
                        <GpTicketId t={t} gpId={g.id} />
                        <span className="mt-0.5 block">
                          <TypeTag g={g} />
                        </span>
                      </td>
                      <td className="w-[12rem] px-2 py-2">
                        {x.fullEdit ? (
                          <span className="grid gap-1">
                            <Input value={x.d?.gpName ?? g.gpName} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { gpName: e.target.value })} className="h-8 text-[0.8125rem]" aria-label={`GP name of ${g.gpCode}`} />
                            <Input value={x.d?.block ?? g.block ?? ""} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { block: e.target.value })} placeholder="Block" className="h-8 text-[0.8125rem]" aria-label={`Block of ${g.gpCode}`} />
                          </span>
                        ) : (
                          <>
                            <span className="block font-medium">{g.gpName}</span>
                            <span className="block text-[0.75rem] text-muted-foreground">{g.block ?? "—"}</span>
                          </>
                        )}
                      </td>
                      <td className="w-[10rem] px-2 py-2.5">
                        <span className="flex items-center gap-1">
                          <span className={cn("font-medium", !g.feName && "text-warning-text")}>{g.feName ?? "FE not mapped"}</span>
                          {canReassign && !g.locked && !g.ndCase?.open && t.status !== "CLOSED" && (
                            <button type="button" onClick={() => setMoving(g)} className="rounded p-0.5 text-primary hover:bg-primary-soft" title="Reassign FE – give this GP to another Field Engineer" aria-label={`Reassign FE of ${g.gpCode}`}>
                              <UserCog className="size-3.5" />
                            </button>
                          )}
                        </span>
                        {g.frtCode && (
                          <span className="mt-0.5 flex flex-wrap items-center gap-1 text-[0.71875rem] text-muted-foreground">
                            <span className="whitespace-nowrap">FRT {g.frtCode}</span>
                            {!g.frtAssigned && <span className="rounded bg-muted px-1 text-[0.625rem] font-semibold" title="No FRT login on this ticket – the FE reports this GP">no login</span>}
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-2.5">
                        <TagCell target={g.target} achieved={x.cum} />
                      </td>
                      <td className="w-[12rem] px-2 py-2">
                        {x.rowEdit ? (
                          <>
                            <GpCategorySelect value={x.cat} disabled={busy} options={x.catOptions} onChange={(v) => set(g.id, { category: v === (g.gpCategory ?? null) ? null : v })} ariaLabel={`Daily achievement of ${g.gpCode}`} />
                            {x.d && (
                              <button
                                type="button"
                                className="mt-1 text-[0.71875rem] font-medium text-muted-foreground hover:text-primary disabled:opacity-50"
                                disabled={busy}
                                onClick={() => setDraft((cur) => Object.fromEntries(Object.entries(cur).filter(([k]) => Number(k) !== g.id)))}
                                title="Undo the unsubmitted change of this GP"
                              >
                                Clear change
                              </button>
                            )}
                          </>
                        ) : x.cat || !x.done ? (
                          <GpCategoryBadge code={x.cat} />
                        ) : (
                          <GpStatusBadge status={g.status} />
                        )}
                        {sub?.submittedBy && !x.d && (
                          <span className="mt-0.5 block text-[0.6875rem] text-muted-foreground" title={sub.submittedAt ? ticketTime(sub.submittedAt) : undefined}>
                            by {sub.submittedByRole} {sub.submittedBy}
                            {g.frtStage === "FE_VERIFIED" ? " · FE verified" : ""}
                          </span>
                        )}
                      </td>
                      <td className="min-w-[11rem] max-w-[15rem] px-2 py-2">
                        {x.textEdit ? (
                          <Input value={x.d?.remark ?? g.remarks ?? ""} maxLength={500} disabled={busy} onChange={(e) => set(g.id, { remark: e.target.value })} placeholder="Remark" className="h-9 text-[0.8125rem]" aria-label={`Remark for ${g.gpCode}`} />
                        ) : (
                          <span className="line-clamp-2" title={g.remarks ?? undefined}>
                            {g.remarks ?? <span className="text-muted-foreground">—</span>}
                          </span>
                        )}
                      </td>
                      <td className="w-[11rem] px-2 py-2">
                        <span className="flex flex-wrap items-center gap-2">
                          <FrtProofChips saved={g.files} draft={x.d?.files ?? []} disabled={busy} onRemove={(i) => set(g.id, { files: (x.d?.files ?? []).filter((_, j) => j !== i) })} />
                          {x.textEdit && (
                            <label
                              className={cn("flex size-10 cursor-pointer items-center justify-center rounded-md border border-dashed border-primary/50 text-primary hover:bg-primary-soft", busy && "pointer-events-none opacity-50")}
                              title="Upload a photo (JPG / PNG) or a document"
                            >
                              <Plus className="size-4" aria-hidden />
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
                                aria-label={`Upload proof for ${g.gpCode}`}
                              />
                            </label>
                          )}
                          {!x.textEdit && g.files.length === 0 && <span className="text-[0.75rem] text-muted-foreground">No proof</span>}
                        </span>
                        {x.needsEvidence && <span className="mt-1 block text-[0.6875rem] font-medium text-warning-text">{EVIDENCE_HINT}</span>}
                      </td>
                      <td className="px-2 py-2">
                        {canAct && (canStep(g, "AM_APPROVE") || canStep(g, "AM_RETURN")) ? (
                          <span className="flex flex-col items-start gap-1">
                            {canStep(g, "AM_APPROVE") && (
                              <button
                                type="button"
                                onClick={() => setAmAct({ action: "AM_APPROVE", gps: [g] })}
                                className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-good px-2 py-1 text-[0.71875rem] font-semibold text-white hover:bg-good/90"
                                title="Approve GP readiness and send to the SME"
                              >
                                <CheckCircle2 className="size-3.5" aria-hidden /> Approve
                              </button>
                            )}
                            {canStep(g, "AM_RETURN") && (
                              <button
                                type="button"
                                onClick={() => setAmAct({ action: "AM_RETURN", gps: [g] })}
                                className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-critical/40 px-2 py-1 text-[0.71875rem] font-semibold text-critical-text hover:bg-critical-soft"
                                title="Return to the FE for correction / recheck"
                              >
                                <Undo2 className="size-3.5" aria-hidden /> Return
                              </button>
                            )}
                          </span>
                        ) : (
                          <span className="text-[0.75rem] text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        <ReviewCell g={g} onTimeline={smeView ? undefined : () => setDetailId(g.id)} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <ReviewDialog
            t={t}
            action={amAct?.action ?? null}
            gps={amAct?.gps ?? []}
            onClose={() => setAmAct(null)}
            onDone={(next, notice) => {
              setAmAct(null);
              setPicked(new Set());
              onChanged(next, notice);
            }}
          />
        </div>
      )}

      {/* GP-wise progress table (scrolls inside the card; the header stays visible) */}
      {!smeView && !frtScope && !feView && !amView && (
      <div className="hidden max-h-[35rem] overflow-auto md:block">
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
              {["GP Code", "GP Name", "Block", ...(showFeCol ? ["FE"] : []), ...(showFrtCol ? ["FRT"] : []), "Type", "Weekly Target", "Achieved", "Remaining Gap", "Daily Achievement", "Remarks", "Proof", "Review", "Action"].map((h) => (
                <th key={h} scope="col" className={cn("px-3 py-2", ["Weekly Target", "Achieved", "Remaining Gap"].includes(h) && "text-right", ["Daily Achievement", "Action"].includes(h) && "text-center", h === "GP Code" && "sticky left-0 z-20 bg-muted")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {shown.map((g) => {
              const x = info(g);
              const { d, done, cat, cum, rowEdit, fullEdit, textEdit, catOptions, pickable } = x;
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
                  <td className="sticky left-0 z-[5] bg-card px-3 py-2">
                    <button type="button" onClick={() => setDetailId(g.id)} className="font-semibold text-primary hover:underline" title="Open the GP details (FE submission, AM approval, review history)">
                      {g.gpCode}
                    </button>
                    <GpTicketId t={t} gpId={g.id} />
                  </td>
                  <td className="min-w-[10.625rem] px-3 py-1.5">
                    {fullEdit ? (
                      <Input value={d?.gpName ?? g.gpName} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { gpName: e.target.value })} className="h-8 text-[0.8125rem]" aria-label={`GP name of ${g.gpCode}`} />
                    ) : (
                      g.gpName
                    )}
                  </td>
                  <td className="min-w-[8.125rem] px-3 py-1.5 text-muted-foreground">
                    {fullEdit ? (
                      <Input value={d?.block ?? g.block ?? ""} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { block: e.target.value })} className="h-8 text-[0.8125rem]" placeholder="Block" aria-label={`Block of ${g.gpCode}`} />
                    ) : (
                      (g.block ?? "—")
                    )}
                  </td>
                  {showFeCol && (
                    <td className={cn("px-3 py-2", !g.feName && "text-warning-text")}>
                      {g.feName ?? "Not mapped"}
                      {canReassign && !g.locked && !g.ndCase?.open && t.status !== "CLOSED" && (
                        <button
                          type="button"
                          onClick={() => setMoving(g)}
                          className="mt-0.5 flex items-center gap-1 rounded px-1 py-0.5 text-[0.71875rem] font-medium text-primary hover:bg-primary-soft"
                          title="Give this GP to another Field Engineer of the ticket"
                        >
                          <UserCog className="size-3.5" aria-hidden /> Reassign FE
                        </button>
                      )}
                    </td>
                  )}
                  {showFrtCol && (
                    <td className="px-3 py-2">
                      {g.frtCode ? (
                        <>
                          <span className="font-medium">{g.frtCode}</span>
                          {!g.frtAssigned && <span className="block text-[0.6875rem] text-muted-foreground" title="No FRT login on this ticket – the FE reports this GP">no FRT login</span>}
                        </>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  )}
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
                      <GpCategorySelect value={cat} disabled={busy} options={catOptions} onChange={(v) => set(g.id, { category: v === (g.gpCategory ?? null) ? null : v })} ariaLabel={`Daily achievement of ${g.gpCode}`} />
                    ) : cat || !done ? (
                      <GpCategoryBadge code={cat} />
                    ) : (
                      <GpStatusBadge status={g.status} />
                    )}
                  </td>
                  <td className="min-w-[12.5rem] px-3 py-1.5">
                    {textEdit ? (
                      <Input value={d?.remark ?? g.remarks ?? ""} maxLength={500} disabled={busy} onChange={(e) => set(g.id, { remark: e.target.value })} placeholder={done ? "Remark" : "Remark / reason if pending"} className="h-8 text-[0.8125rem]" aria-label={`Remark for ${g.gpCode}`} />
                    ) : (
                      <span className="text-[0.8125rem]">{g.remarks ?? <span className="text-muted-foreground">No Remarks</span>}</span>
                    )}
                  </td>
                  <td className="min-w-[11.875rem] max-w-[15rem] px-3 py-1.5">{proofCell(g, x)}</td>
                  <td className="px-3 py-1.5">
                    <ReviewCell g={g} onTimeline={smeView ? undefined : () => setDetailId(g.id)} />
                  </td>
                  <td className="px-3 py-2 text-center">
                    {checkButtons(g, x) && <span className="mb-1 flex justify-center">{checkButtons(g, x)}</span>}
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

      {/* phones: one card per GP (the same rules and actions as the table rows) */}
      {!smeView && (
        <ul className="divide-y divide-border md:hidden" aria-label="GP-wise task progress">
          {shown.map((g) => {
            const x = info(g);
            return (
              <li key={g.id} className={cn("space-y-2 px-4 py-3 text-[0.8125rem]", x.d && "bg-primary-soft/30", g.review === "RETURNED" && !x.d && "bg-critical-soft/30")}>
                <div className="flex items-start gap-2">
                  {roles.length > 0 && (
                    <input
                      type="checkbox"
                      aria-label={`Select ${g.gpCode} for review`}
                      disabled={!x.pickable}
                      checked={picked.has(g.id)}
                      onChange={(e) =>
                        setPicked((cur) => {
                          const next = new Set(cur);
                          if (e.target.checked) next.add(g.id);
                          else next.delete(g.id);
                          return next;
                        })
                      }
                      className="mt-0.5 size-4 shrink-0 accent-[var(--primary)] disabled:opacity-30"
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <button type="button" onClick={() => setDetailId(g.id)} className="text-left font-semibold text-primary hover:underline">
                      {g.gpCode} · {g.gpName}
                    </button>
                    <p className="text-[0.75rem] text-muted-foreground">
                      {g.block ?? "—"}
                      {showFeCol && g.feName && <> · FE {g.feName}</>}
                      {showFrtCol && g.frtCode && <> · FRT {g.frtCode}</>}
                      {g.kind !== "WEEK" && <> · {g.kind === "ADDED" ? "Added" : "Pending"}</>}
                    </p>
                  </div>
                  <span className="shrink-0 whitespace-nowrap text-right text-[0.75rem] font-semibold">
                    {g.target} / <span className={cn(x.cum >= g.target && "text-good-text")}>{x.cum}</span> /{" "}
                    <span className={g.target - x.cum > 0 ? "text-critical-text" : "text-good-text"}>{g.target - x.cum}</span>
                    <span className="block text-[0.625rem] font-normal text-muted-foreground">Target / Ach. / Gap</span>
                  </span>
                </div>
                {x.rowEdit ? (
                  <div className="space-y-2">
                    <GpCategorySelect value={x.cat} disabled={busy} options={x.catOptions} onChange={(v) => set(g.id, { category: v === (g.gpCategory ?? null) ? null : v })} ariaLabel={`Daily achievement of ${g.gpCode}`} />
                    {x.textEdit && (
                      <Input value={x.d?.remark ?? g.remarks ?? ""} maxLength={500} disabled={busy} onChange={(e) => set(g.id, { remark: e.target.value })} placeholder="Remark" className="h-9 text-[0.8125rem]" aria-label={`Remark for ${g.gpCode}`} />
                    )}
                    {x.fullEdit && (
                      <details className="text-[0.75rem]">
                        <summary className="cursor-pointer font-medium text-primary">{frtScope ? "Correct GP code / name / block" : "Correct GP name / block"}</summary>
                        <div className="mt-1.5 grid gap-2">
                          {frtScope && (
                            <Input value={x.d?.gpCode ?? g.gpCode} maxLength={40} disabled={busy} onChange={(e) => set(g.id, { gpCode: e.target.value })} className="h-9 text-[0.8125rem]" aria-label={`GP code of ${g.gpCode}`} />
                          )}
                          <Input value={x.d?.gpName ?? g.gpName} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { gpName: e.target.value })} className="h-9 text-[0.8125rem]" aria-label={`GP name of ${g.gpCode}`} />
                          <Input value={x.d?.block ?? g.block ?? ""} maxLength={160} disabled={busy} onChange={(e) => set(g.id, { block: e.target.value })} placeholder="Block" className="h-9 text-[0.8125rem]" aria-label={`Block of ${g.gpCode}`} />
                        </div>
                      </details>
                    )}
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    {x.cat || !x.done ? <GpCategoryBadge code={x.cat} /> : <GpStatusBadge status={g.status} />}
                    {g.remarks && <span className="min-w-0 break-words text-[0.78125rem]">{g.remarks}</span>}
                  </div>
                )}
                <div>{proofCell(g, x)}</div>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <ReviewCell g={g} onTimeline={smeView ? undefined : () => setDetailId(g.id)} />
                  <div className="flex flex-wrap items-center gap-1">
                    {checkButtons(g, x)}
                    {x.rowEdit && x.d && (
                      <button type="button" className="rounded px-2 py-1 text-[0.75rem] font-medium text-primary hover:bg-primary-soft disabled:opacity-50" disabled={busy} onClick={() => setDraft((cur) => Object.fromEntries(Object.entries(cur).filter(([k]) => Number(k) !== g.id)))}>
                        Clear
                      </button>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {(frtScope || scoped) && (
        <CameraCapture open={camFor !== null} gpCode={camFor?.gpCode ?? ""} gpName={camFor?.gpName} onClose={() => setCamFor(null)} onCapture={(f) => camFor && addCameraFile(camFor.id, f)} />
      )}
      {!smeView && <GpDetailDialog t={t} g={task.gps.find((g) => g.id === detailId) ?? null} roles={roles} onClose={() => setDetailId(null)} onChanged={onChanged} />}
      {canReassign && <ReassignDialog t={t} g={moving} onClose={() => setMoving(null)} onChanged={onChanged} />}
      {canCheck && <FeCheckDialog t={t} check={checking} onClose={() => setChecking(null)} onChanged={onChanged} />}

      {/* GP rows added by the FE / Area Manager / FRT (target 1 each, sent with the submission; an FRT's GP goes to its FE) */}
      {editable && (
        <div id="add-gps" className="scroll-mt-24 border-t border-border px-5 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">
              Add GPs{" "}
              <span className="font-normal normal-case">
                – a GP missing from the list; its details come from the master data when the code is known (target 1 each){frtScope ? " – your FE checks it like your other GPs" : ""}
              </span>
            </p>
            <Button
              size="sm"
              variant="outline"
              disabled={busy || rows.length >= 50}
              onClick={() => setRows((cur) => [...cur, { key: Date.now() + cur.length, gpCode: "", gpName: "", block: "", category: null, remark: "", files: [] }])}
            >
              <Plus /> Add GP row
            </Button>
          </div>
          {rows.length > 0 && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full min-w-[60rem] text-[0.8125rem]">
                <thead>
                  <tr className="text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                    {["GP Code", "GP Name", "Block", "Daily Achievement", "Remarks", "Photo", ""].map((h) => (
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
                          <GpCategorySelect value={r.category} disabled={busy} options={frtScope ? ["A", "C", "D"] : undefined} onChange={(v) => upd({ category: v as NewRow["category"] })} ariaLabel="Daily achievement of the new GP" />
                        </td>
                        <td className="px-2 py-1.5">
                          <Input value={r.remark} maxLength={500} disabled={busy} onChange={(e) => upd({ remark: e.target.value })} placeholder="Remark" className="h-8 text-[0.8125rem]" aria-label="New GP remark" />
                        </td>
                        <td className="min-w-[10rem] px-2 py-1.5">
                          {r.files.map((f, i) => (
                            <span key={`${f.name}-${i}`} className="flex items-center gap-1 text-[0.75rem] text-[var(--series-7)]">
                              <Paperclip className="size-3.5 shrink-0" aria-hidden />
                              <span className="min-w-0 flex-1 truncate" title={f.name}>
                                {f.name}
                              </span>
                              <button type="button" disabled={busy} onClick={() => upd({ files: r.files.filter((_, j) => j !== i) })} className="rounded p-0.5 hover:bg-accent" aria-label={`Remove ${f.name}`}>
                                <X className="size-3" />
                              </button>
                            </span>
                          ))}
                          {r.category && (r.remark.trim().length < MIN_REMARK || !r.files.some(isPhoto)) && <span className="block text-[0.6875rem] font-medium text-critical-text">{EVIDENCE_HINT}</span>}
                          <label className={cn("inline-flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 text-[0.75rem] font-medium text-primary hover:bg-primary-soft", busy && "pointer-events-none opacity-50")}>
                            <Paperclip className="size-3.5" aria-hidden /> Attach
                            <input
                              type="file"
                              multiple
                              accept={PROOF_ACCEPT}
                              className="sr-only"
                              disabled={busy}
                              onChange={(e) => {
                                const picked = Array.from(e.target.files ?? []);
                                e.target.value = "";
                                const big = picked.find((f) => f.size > MAX_FILE_MB * 1024 * 1024);
                                if (big) return setError(`${big.name}: larger than ${MAX_FILE_MB} MB`);
                                if (r.files.length + picked.length > MAX_GP_FILES) return setError(`New GP: at most ${MAX_GP_FILES} proof documents per submission`);
                                setError(null);
                                upd({ files: [...r.files, ...picked] });
                              }}
                              aria-label="Attach a photo for the new GP"
                            />
                          </label>
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
        <div className={cn("flex flex-col gap-3 border-t border-border px-5 py-4 lg:flex-row lg:items-end", (frtScope || feView || amView) && "sticky bottom-0 z-20 bg-card shadow-[0_-4px_12px_rgba(0,0,0,0.06)]")}>
          <label className="flex-1 space-y-1">
            <span className="text-[0.8125rem] font-medium">Note for today (optional)</span>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={2000} disabled={busy} className={TEXTAREA} placeholder="What was done today…" />
          </label>
          <div className="flex flex-col items-end gap-1">
            <span className="text-xs text-muted-foreground">
              {sent !== null
                ? `Uploading proof documents… ${Math.round(sent * 100)}%`
                : ndPending.length
                  ? `Locked – submit E1 / E2 of ${ndPending.map((c) => c.ref).join(", ")} first`
                  : badRow
                  ? `"${badRow.gpCode.trim()}" is not a valid GP code`
                  : lacking.length
                    ? `${EVIDENCE_HINT}: ${lacking.slice(0, 5).join(", ")}${lacking.length > 5 ? ` (+${lacking.length - 5})` : ""}`
                  : emptyName
                    ? "A GP name cannot be empty"
                  : badCode
                    ? `"${String(badCode.gpCode)}" is not a valid GP code`
                    : frtScope && (changed.length || newGps.length)
                      ? `${changed.length} GP${changed.length === 1 ? "" : "s"} ready to submit${newGps.length ? ` · ${newGps.length} new GP${newGps.length === 1 ? "" : "s"}` : ""} · ${allProofs.length} photo${allProofs.length === 1 ? "" : "s"}`
                    : changed.length || newGps.length
                      ? `${classified} status change${classified === 1 ? "" : "s"} · ${edits} corrected · ${changed.length - classified} other line${changed.length - classified === 1 ? "" : "s"} · ${allProofs.length} proof file${allProofs.length === 1 ? "" : "s"} · ${newGps.length} new GP${newGps.length === 1 ? "" : "s"}`
                      : frtScope
                        ? "Choose a status, write a remark and add a photo for your GPs"
                        : "Choose a status for the GPs, correct their details, write a remark, attach proof or add a GP"}
            </span>
            <Button variant="primary" onClick={submit} disabled={busy || ndPending.length > 0 || (changed.length === 0 && newGps.length === 0) || !!badRow || emptyName || !!badCode || lacking.length > 0}>
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

/** FE-wise progress of the task (Area Manager, CBH / SME and admin view): target, achieved, gap and where the GPs wait –
 * the FRT's report for the FE's verification, the Area Manager's approval, returned by the AM, not reported yet. */
function FeSplit({ fes }: { fes: NonNullable<TicketTask["fes"]> }) {
  const num = (n: number, tone: string) => <td className={cn("px-2 py-1.5 text-right", n ? `font-semibold ${tone}` : "text-muted-foreground")}>{n}</td>;
  return (
    <div className="border-b border-border px-5 py-3">
      <p className="mb-2 text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">Field Engineer-wise</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[52rem] text-[0.78125rem]">
          <thead>
            <tr className="text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
              {["Field Engineer", "Target", "Achieved", "Gap", "Pending FE Verification", "Awaiting AM", "Returned", "Not classified"].map((h) => (
                <th key={h} scope="col" className={cn("px-2 py-1", h !== "Field Engineer" && "text-right")}>
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
                <td className="px-2 py-1.5 text-right">{f.target}</td>
                <td className="px-2 py-1.5 text-right font-semibold text-good-text">{f.achieved}</td>
                <td className={cn("px-2 py-1.5 text-right font-semibold", f.gap > 0 ? "text-critical-text" : "text-good-text")}>{f.gap}</td>
                {num(f.pendingFeGps ?? 0, "text-warning-text")}
                {num(f.awaitingGps ?? 0, "text-warning-text")}
                {num(f.returnedGps ?? 0, "text-critical-text")}
                <td className="px-2 py-1.5 text-right text-muted-foreground">{f.notClassified ?? f.gps}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** FRT-wise target and progress, grouped by FE (FE first, then the FRTs under that FE). */
function FrtSplit({ frts }: { frts: TicketTaskFrt[] }) {
  const fe = (f: TicketTaskFrt) => f.fes.join(", ");
  const rows = [...frts].sort((x, y) => (fe(x) === "" ? 1 : 0) - (fe(y) === "" ? 1 : 0) || fe(x).localeCompare(fe(y)) || x.code.localeCompare(y.code));
  const num = (n: number, tone: string) => <td className={cn("px-2 py-1.5 text-right", n ? `font-semibold ${tone}` : "text-muted-foreground")}>{n}</td>;
  return (
    <div className="border-b border-border px-5 py-3">
      <p className="mb-2 text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">FRT-wise target</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[56rem] text-[0.78125rem]">
          <thead>
            <tr className="text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
              {["FE", "FRT", "Target", "Achieved", "Gap", "Not classified", "Pending FE check", "Returned to FRT", "Verified by FE"].map((h) => (
                <th key={h} scope="col" className={cn("px-2 py-1", !["FE", "FRT"].includes(h) && "text-right")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {rows.map((f) => (
              <tr key={f.code} className="border-t border-border/60">
                <td className="px-2 py-1.5 font-semibold">{fe(f) || <span className="font-normal text-muted-foreground">—</span>}</td>
                <td className="px-2 py-1.5">
                  <b className="font-semibold">{f.code}</b>
                  {f.names.length > 0 ? (
                    <span className="text-muted-foreground"> · {f.names.join(", ")}</span>
                  ) : (
                    <span className="ml-1.5 rounded bg-muted px-1.5 py-0.5 text-[0.65625rem] font-semibold text-muted-foreground" title="No FRT login for this code – the FE reports these GPs">
                      no FRT login
                    </span>
                  )}
                </td>
                <td className="px-2 py-1.5 text-right">{f.target}</td>
                <td className="px-2 py-1.5 text-right font-semibold text-good-text">{f.achieved}</td>
                <td className={cn("px-2 py-1.5 text-right font-semibold", f.gap > 0 ? "text-critical-text" : "text-good-text")}>{f.gap}</td>
                <td className="px-2 py-1.5 text-right text-muted-foreground">{f.notClassified}</td>
                {num(f.pendingFe, "text-warning-text")}
                {num(f.returnedFrt, "text-critical-text")}
                {num(f.verified, "text-good-text")}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** FE (or admin): check the FRT's Daily Achievement of one GP – or of several picked GPs (`all`, one remark) – Verify
 * (to the Area Manager) or Return to FRT, with a remark (backend: task.fe_check, all or none). The FRT's remark and
 * proof of a single GP are shown to check against. */
function FeCheckDialog({ t, check, onClose, onChanged }: { t: TicketDetail; check: { g: TicketTaskGp; action: FeCheckAction; all?: TicketTaskGp[] } | null; onClose: () => void; onChanged: (next: TicketDetail, notice: Notice) => void }) {
  const [remark, setRemark] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const g = check?.g ?? null;
  const verify = check?.action === "FE_VERIFY";
  const close = () => {
    setRemark("");
    setError(null);
    onClose();
  };
  const save = async () => {
    if (!check || remark.trim().length < MIN_REMARK) return;
    setBusy(true);
    setError(null);
    try {
      const list = check.all?.length ? check.all : [check.g];
      const next = await ticketApi.feCheck(t.id, { taskGpIds: list.map((x) => x.id), action: check.action, remark: remark.trim() });
      close();
      const what = list.length === 1 ? `GP ${list[0].gpCode}` : `${list.length} GPs`;
      onChanged(next, { ok: true, text: verify ? `${what} verified and sent to the Area Manager.` : `${what} returned to the FRT with your reason.` });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the check");
    } finally {
      setBusy(false);
    }
  };
  const sub = g?.feSubmission;
  const many = (check?.all?.length ?? 0) > 1 ? check!.all! : null;
  return (
    <Dialog open={check !== null} onOpenChange={(o) => !o && !busy && close()}>
      <DialogContent className="max-w-lg">
        {g && (
          <form
            className="space-y-4 p-5"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <div>
              <DialogTitle className="text-lg font-bold">{verify ? "Verify FRT's Daily Achievement" : "Return to FRT"}</DialogTitle>
              <DialogDescription className="mt-1 text-sm text-muted-foreground">
                {verify
                  ? "Check the FRT's photo and remark. Verified GPs go to the Area Manager for approval."
                  : "The GP goes back to the FRT, who corrects it and submits it again with a new photo."}
              </DialogDescription>
            </div>
            {many ? (
              <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-[0.8125rem]">
                <b>{many.length} GPs:</b> {many.map((x) => x.gpCode).join(", ")}
              </p>
            ) : (
            <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-[0.8125rem]">
              <dt className="text-muted-foreground">GP</dt>
              <dd className="font-semibold">
                {g.gpCode} · {g.gpName}
              </dd>
              <dt className="text-muted-foreground">FRT</dt>
              <dd>{g.frtCode ?? "—"}</dd>
              <dt className="text-muted-foreground">Daily Achievement</dt>
              <dd>
                <GpCategoryBadge code={sub?.category ?? g.gpCategory ?? null} />
              </dd>
              <dt className="text-muted-foreground">FRT remark</dt>
              <dd>{sub?.remark ?? g.remarks ?? "—"}</dd>
              <dt className="text-muted-foreground">Submitted</dt>
              <dd>{sub ? `${sub.submittedBy ?? "—"}${sub.submittedAt ? ` · ${ticketTime(sub.submittedAt)}` : ""}` : "—"}</dd>
              <dt className="text-muted-foreground">Proof</dt>
              <dd>{(sub?.files ?? g.files).length ? <ProofList files={sub?.files ?? g.files} compact /> : <span className="text-critical-text">No proof uploaded</span>}</dd>
            </dl>
            )}
            <label className="block space-y-1">
              <span className="text-[0.8125rem] font-medium">
                {verify ? "Your check remark" : "Reason for returning"} <span className="text-critical-text">*</span>
              </span>
              <textarea
                value={remark}
                onChange={(e) => setRemark(e.target.value)}
                rows={3}
                maxLength={500}
                disabled={busy}
                className={TEXTAREA}
                placeholder={verify ? "e.g. Photo and remark checked – work is complete" : "e.g. Photo is not of this GP"}
              />
            </label>
            {error && (
              <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={close} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={busy || remark.trim().length < MIN_REMARK}>
                {busy ? <Loader2 className="animate-spin" /> : verify ? <CheckCircle2 /> : <Undo2 />} {verify ? "Verify & send to AM" : "Return to FRT"}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
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

/** Area Manager / admin: give one GP to another Field Engineer of the ticket. Only the GP's FE changes – target,
 * category, daily history, proof and review steps stay; the step is kept in the GP's history (backend: task.reassign_gp). */
function ReassignDialog({ t, g, onClose, onChanged }: { t: TicketDetail; g: TicketTaskGp | null; onClose: () => void; onChanged: (next: TicketDetail, notice: Notice) => void }) {
  const options = (t.task?.feOptions ?? []).filter((o) => o.name !== g?.feName);
  const [to, setTo] = useState("");
  const [remark, setRemark] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    setTo("");
    setRemark("");
    setError(null);
    onClose();
  };
  const save = async () => {
    if (!g || !to) return;
    setBusy(true);
    setError(null);
    try {
      const next = await ticketApi.reassignGp(t.id, g.id, { recipientId: Number(to), remark: remark.trim() || undefined });
      const name = options.find((o) => String(o.recipientId) === to)?.name ?? "the new FE";
      close();
      onChanged(next, { ok: true, text: `GP ${g.gpCode} reassigned to FE ${name}. Both FEs have been notified; its history is kept.` });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reassign the GP");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={g !== null} onOpenChange={(o) => !o && !busy && close()}>
      <DialogContent className="max-w-lg">
        {g && (
          <form
            className="space-y-4 p-5"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <div>
              <DialogTitle className="text-lg font-bold">Reassign FE</DialogTitle>
              <DialogDescription className="mt-1 text-sm text-muted-foreground">
                The GP moves to the chosen Field Engineer. Its target, category, daily history, proof and review steps stay as they are.
              </DialogDescription>
            </div>
            <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-[0.8125rem]">
              <dt className="text-muted-foreground">GP Code</dt>
              <dd className="font-semibold">{g.gpCode}</dd>
              <dt className="text-muted-foreground">GP Name</dt>
              <dd>{g.gpName}</dd>
              <dt className="text-muted-foreground">Current FE</dt>
              <dd className={cn(!g.feName && "text-warning-text")}>{g.feName ?? "Not mapped"}</dd>
            </dl>
            <label className="block space-y-1">
              <span className="text-[0.8125rem] font-medium">
                New FE <span className="text-critical-text">*</span>
              </span>
              {options.length ? (
                <Select
                  ariaLabel="New Field Engineer"
                  value={to}
                  onValueChange={(v) => setTo(v ?? "")}
                  placeholder="Choose the Field Engineer"
                  options={options.map((o) => ({ value: String(o.recipientId), label: `${o.name} · ${o.email}` }))}
                  className="w-full"
                />
              ) : (
                <p className="text-[0.8125rem] text-warning-text">No other Field Engineer with a dashboard account is on this ticket.</p>
              )}
            </label>
            <label className="block space-y-1">
              <span className="text-[0.8125rem] font-medium">Reason (optional)</span>
              <textarea value={remark} onChange={(e) => setRemark(e.target.value)} rows={2} maxLength={500} disabled={busy} className={TEXTAREA} placeholder="e.g. FE on leave this week" />
            </label>
            {error && (
              <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={close} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={busy || !to}>
                {busy ? <Loader2 className="animate-spin" /> : <UserCog />} Confirm Reassignment
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
