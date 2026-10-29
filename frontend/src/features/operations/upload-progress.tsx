"use client";

import { AlertTriangle, Check, CheckCircle2, Loader2, X, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { EscalationImportRun } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate, formatDuration } from "@/lib/utils/format";
import type { IngestionRun } from "@/types";

/** One file the user picked with "Upload data files", from sending it until its import finishes. */
export interface UploadJob {
  key: string;
  name: string;
  size: number;
  /** uploading = file is being sent / checked; rejected = the server (or the browser check) refused it; accepted = import started */
  phase: "uploading" | "rejected" | "accepted";
  /** Share of the file sent so far (0–1) */
  progress: number;
  kind?: "master" | "escalation";
  /** Id of the import run (master: Import history id; escalation: Escalation Matrix id) */
  runId?: string;
  error?: string;
  /** Client time (ms) when the server accepted the file and processing began */
  processingSince?: number;
}

type Tone = "good" | "warning" | "critical";

export type JobOutcome =
  | { state: "uploading" }
  | { state: "checking" }
  | { state: "processing" }
  | { state: "done"; tone: Tone; title: string; detail: string; runId?: string };

/** Where a job stands, read from the latest Import history / Escalation Matrix lists (the server is the source of truth). */
export function jobOutcome(job: UploadJob, runs: IngestionRun[] | undefined, escalation: EscalationImportRun[] | undefined): JobOutcome {
  if (job.phase === "rejected") return { state: "done", tone: "critical", title: "Not uploaded", detail: job.error ?? "The file was not accepted." };
  if (job.phase === "uploading") return job.progress < 1 ? { state: "uploading" } : { state: "checking" };

  if (job.kind === "escalation") {
    const x = escalation?.find((r) => r.id === job.runId);
    if (!x || x.status === "PROCESSING") return { state: "processing" };
    if (x.status === "FAILED") return { state: "done", tone: "critical", title: "Escalation Matrix import failed", detail: x.message ?? "The file could not be read." };
    const parts = [`${formatCount(x.rows)} GPs loaded`];
    if (x.rejected) parts.push(`${formatCount(x.rejected)} rows rejected`);
    parts.push(x.isActive ? "now used by Field Team & Escalation" : "not the active Escalation Matrix");
    return { state: "done", tone: x.isActive && !x.rejected ? "good" : "warning", title: x.isActive ? "Escalation Matrix loaded" : "Escalation Matrix loaded, not active", detail: parts.join(" · ") };
  }

  const r = runs?.find((x) => x.id === job.runId);
  if (!r || r.status === "PROCESSING") return { state: "processing" };
  if (r.status === "FAILED") {
    return { state: "done", tone: "critical", title: "Import failed – dashboards still show the previous data", detail: r.message ?? "See the data-quality issues below.", runId: r.id };
  }
  const facts = [`${formatCount(r.accepted)} records accepted`];
  if (r.rejected) facts.push(`${formatCount(r.rejected)} rejected`);
  if (r.dataAsOf) facts.push(`data as of ${formatDate(r.dataAsOf)}`);
  if (r.durationSec != null) facts.push(`took ${formatDuration(r.durationSec)}`);
  if (!r.isActive) {
    return { state: "done", tone: "warning", title: "Imported, but not made live", detail: [r.message, facts.join(" · ")].filter(Boolean).join(" "), runId: r.id };
  }
  return {
    state: "done",
    tone: r.status === "PARTIAL" ? "warning" : "good",
    title: r.status === "PARTIAL" ? "Imported and live – some rows were rejected" : "Imported and live – dashboards updated",
    detail: facts.join(" · "),
    runId: r.id,
  };
}

const STEPS = ["Upload", "File check", "Processing", "Done"] as const;
const TONE_BOX: Record<Tone, string> = {
  good: "border-good/40 bg-good-soft text-good-text",
  warning: "border-warning/50 bg-warning-soft text-warning-text",
  critical: "border-critical/30 bg-critical-soft text-critical-text",
};
const TONE_ICON = { good: CheckCircle2, warning: AlertTriangle, critical: XCircle } as const;

function sizeLabel(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function clock(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Live status of the files just uploaded: a step strip per file, then the result in plain words. */
export function UploadPanel({
  jobs,
  runs,
  escalation,
  now,
  onClear,
  onShowRun,
}: {
  jobs: UploadJob[];
  runs: IngestionRun[] | undefined;
  escalation: EscalationImportRun[] | undefined;
  now: number;
  onClear: () => void;
  onShowRun: (runId: string) => void;
}) {
  if (!jobs.length) return null;
  const outcomes = jobs.map((j) => jobOutcome(j, runs, escalation));
  const busy = outcomes.some((o) => o.state !== "done");
  return (
    <section aria-labelledby="ops-upload-status" className="overflow-hidden rounded-xl border border-primary/30 bg-card shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-primary-soft/40 px-5 py-3">
        <h2 id="ops-upload-status" className="flex items-center gap-2 text-sm font-semibold">
          {busy ? <Loader2 className="size-4 animate-spin text-primary" aria-hidden /> : <CheckCircle2 className="size-4 text-good" aria-hidden />}
          {busy ? "Upload in progress – you can stay on this page, it updates by itself" : "Upload finished"}
        </h2>
        {!busy && (
          <Button size="icon-sm" variant="ghost" onClick={onClear} aria-label="Close upload status">
            <X />
          </Button>
        )}
      </div>
      <ul className="divide-y divide-border" aria-live="polite">
        {jobs.map((job, i) => (
          <JobRow key={job.key} job={job} outcome={outcomes[i]} now={now} onShowRun={onShowRun} />
        ))}
      </ul>
    </section>
  );
}

function JobRow({ job, outcome, now, onShowRun }: { job: UploadJob; outcome: JobOutcome; now: number; onShowRun: (runId: string) => void }) {
  const failedAt = outcome.state === "done" && job.phase === "rejected" ? (job.progress < 1 && job.error?.startsWith("Cannot reach") ? 0 : 1) : null;
  const current = { uploading: 0, checking: 1, processing: 2, done: 4 }[outcome.state];
  const kindLabel = job.kind === "escalation" ? "Escalation Matrix" : job.kind === "master" ? "Master data" : null;
  const elapsed = job.processingSince != null && now >= job.processingSince ? clock(now - job.processingSince) : null;

  return (
    <li className="space-y-3 px-5 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <p className="min-w-0 break-all text-sm font-medium">
          {job.name}
          <span className="ml-2 text-xs font-normal text-muted-foreground">
            {sizeLabel(job.size)}
            {kindLabel && ` · ${kindLabel}`}
          </span>
        </p>
        <p className="text-xs text-muted-foreground">
          {outcome.state === "uploading" && `Sending file… ${Math.round(job.progress * 100)}%`}
          {outcome.state === "checking" && "Checking the file…"}
          {outcome.state === "processing" && `Processing${elapsed ? ` · ${elapsed}` : ""} – large files can take a few minutes`}
        </p>
      </div>

      <ol className="grid grid-cols-4 gap-2" aria-label={`Progress of ${job.name}`}>
        {STEPS.map((label, s) => {
          const failed = failedAt === s;
          const done = !failed && (failedAt != null ? s < failedAt : s < current);
          const active = failedAt == null && s === current;
          return (
            <li key={label} className="min-w-0" aria-current={active ? "step" : undefined}>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full transition-[width] duration-300",
                    failed ? "bg-critical" : done ? "bg-good" : active ? "bg-primary" : "bg-transparent",
                    active && s !== 0 && "animate-pulse",
                  )}
                  style={{ width: failed || done ? "100%" : active ? (s === 0 ? `${Math.max(4, Math.round(job.progress * 100))}%` : "100%") : "0%" }}
                />
              </div>
              <p className={cn("mt-1 flex items-center gap-1 truncate text-[11.5px]", active ? "font-semibold text-foreground" : failed ? "text-critical-text" : "text-muted-foreground")}>
                {done && <Check className="size-3 shrink-0 text-good" aria-hidden />}
                {failed && <XCircle className="size-3 shrink-0" aria-hidden />}
                {active && <Loader2 className="size-3 shrink-0 animate-spin text-primary" aria-hidden />}
                {label}
              </p>
            </li>
          );
        })}
      </ol>

      {outcome.state === "done" && <ResultBox outcome={outcome} onShowRun={onShowRun} />}
    </li>
  );
}

function ResultBox({ outcome, onShowRun }: { outcome: Extract<JobOutcome, { state: "done" }>; onShowRun: (runId: string) => void }) {
  const Icon = TONE_ICON[outcome.tone];
  return (
    <div role={outcome.tone === "critical" ? "alert" : "status"} className={cn("flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3 text-sm", TONE_BOX[outcome.tone])}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{outcome.title}</p>
        <p className="mt-0.5 break-words text-[13px] opacity-90">{outcome.detail}</p>
      </div>
      {outcome.runId && (
        <Button size="sm" variant="outline" onClick={() => onShowRun(outcome.runId!)}>
          {outcome.tone === "good" ? "View changes" : "View details"}
        </Button>
      )}
    </div>
  );
}

/** Small pop-up in the corner when a file finishes, so it is noticed even after scrolling away. */
export function UploadToasts({ items, onClose }: { items: { key: string; name: string; tone: Tone; title: string }[]; onClose: (key: string) => void }) {
  if (!items.length) return null;
  return (
    <div className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-end gap-2 sm:left-auto sm:w-96">
      {items.map((t) => {
        const Icon = TONE_ICON[t.tone];
        return (
          <div key={t.key} role="status" className={cn("pointer-events-auto flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-lg", TONE_BOX[t.tone])}>
            <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="font-semibold">{t.title}</p>
              <p className="truncate text-xs opacity-90">{t.name}</p>
            </div>
            <button type="button" className="rounded p-0.5 opacity-70 hover:opacity-100" onClick={() => onClose(t.key)} aria-label="Dismiss">
              <X className="size-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
