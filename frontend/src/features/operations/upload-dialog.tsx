"use client";

import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, FileUp, Loader2, XCircle } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/controls";
import { DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { adminApi, type UploadIssue, type UploadKind, type UploadPreview } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";

/** What each upload must look like – mirrors the backend importer (column_map.py); the backend checks it again. */
const FORMATS: Record<UploadKind, { label: string; sheet: string; header: string; required: string; periods?: string; templates: { label: string; href: string }[] }> = {
  master: {
    label: "Master Data workbook",
    sheet: "“GP Wise Data” and “Master Block” (both required)",
    header: "found in the first 15 rows (row 3 / row 4 in the template)",
    required: "every column of the PAGMAS template – 41 fixed columns in GP Wise Data, 24 in Master Block – with exactly the template names (any order); see the template's Read Me",
    periods: "added as the data moves on, never renamed: one date per day after the W-nn columns, W-nn with its 7-day dates in the row above, the 1st of each month, Mon'YY (AMC), month / WK-nn status; Master Block month and week columns",
    templates: [
      { label: "Blank template", href: "/api/v1/ingestion/template/master.xlsx" },
      { label: "Sample (2 example rows)", href: "/api/v1/ingestion/template/master.xlsx?sample=true" },
    ],
  },
  escalation: {
    label: "Escalation Matrix",
    sheet: "any sheet with the columns below (“All” in the template)",
    header: "found in the first 15 rows (row 1 in the template)",
    required: "Circle, GP Code, FRT Code, FE Name",
    templates: [
      { label: "Blank template", href: "/templates/Escalation%20Matrix%20Template.xlsx" },
      { label: "Sample (2 example rows)", href: "/templates/Escalation%20Matrix%20Sample.xlsx" },
    ],
  },
};
const STAGE_LABEL: Record<UploadPreview["stage"], string> = { ok: "Ready", file: "File check", kind: "File type", duplicate: "Already imported", template: "Not the PAGMAS template", structure: "Sheet / columns" };
const ACCEPT = ".xlsb,.xlsx";
type Sev = "all" | UploadIssue["severity"];

/**
 * Data Operations → Upload: choose the file type, pick the file, read the validation report, then confirm.
 * Step 1 stages and validates the file on the server (nothing is imported); "Confirm import" imports exactly that
 * file; "Cancel" deletes it. The browser only pre-filters the type – every rule is enforced by the backend.
 */
export function UploadDialog({ onConfirmed, onClose, onCheckColumns }: { onConfirmed: (r: { id: string; kind: UploadKind; fileName: string; size: number }) => void; onClose: () => void; onCheckColumns: (file: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<UploadKind | undefined>(undefined);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [report, setReport] = useState<UploadPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const busy = progress !== null || confirming;
  const fmt = kind ? FORMATS[kind] : null;

  const discard = () => {
    if (report?.token) void adminApi.discardUpload(report.token).catch(() => undefined);
  };
  const reset = () => {
    discard();
    setReport(null);
    setFile(null);
    setError(null);
  };
  const pick = (f: File | undefined) => {
    if (!f) return;
    reset();
    if (!/\.(xlsb|xlsx)$/i.test(f.name)) {
      setError(/\.xlsm$/i.test(f.name) ? "Macro workbooks (.xlsm) are not accepted – save the file as .xlsx or .xlsb and choose it again." : "Choose an Excel workbook (.xlsx or .xlsb).");
      return;
    }
    if (f.size === 0) {
      setError("The file is empty (0 bytes).");
      return;
    }
    setFile(f);
  };
  const validate = async () => {
    if (!kind || !file) return;
    setError(null);
    setProgress(0);
    try {
      setReport(await adminApi.previewUpload(file, kind, (p) => setProgress(p)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The file could not be checked");
    } finally {
      setProgress(null);
    }
  };
  const confirm = async () => {
    if (!report?.token || !file) return;
    setConfirming(true);
    setError(null);
    try {
      const r = await adminApi.confirmUpload(report.token);
      onConfirmed({ id: r.id, kind: r.kind, fileName: r.fileName, size: file.size });
    } catch (e) {
      setError(e instanceof Error ? e.message : "The import could not be started");
      setConfirming(false);
    }
  };
  const close = () => {
    if (busy) return;
    discard();
    onClose();
  };

  return (
    <DialogContent className="top-[4vh] flex max-h-[92vh] max-w-4xl flex-col" onEscapeKeyDown={(e) => busy && e.preventDefault()} onInteractOutside={(e) => e.preventDefault()}>
      <div className="border-b border-border px-6 pb-3 pt-5">
        <DialogTitle className="text-lg font-bold">Upload data file</DialogTitle>
        <DialogDescription className="mt-0.5 text-[0.8125rem] text-muted-foreground">
          Choose what the file is, pick it and read the check report – nothing changes on the dashboard until you press “Confirm import”.
        </DialogDescription>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-4">
        {/* 1 · file type */}
        <div className="grid gap-3 sm:grid-cols-[16rem_minmax(0,1fr)] sm:items-start">
          <label className="space-y-1">
            <span className="text-xs font-semibold text-foreground/75">File type *</span>
            <Select
              ariaLabel="File type"
              value={kind}
              onValueChange={(v) => {
                reset();
                setKind(v as UploadKind);
              }}
              options={[
                { value: "master", label: "Master Data workbook" },
                { value: "escalation", label: "Escalation Matrix" },
              ]}
              placeholder="Select the file type"
              className="w-full"
              disabled={busy}
            />
          </label>
          {fmt ? (
            <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-[0.78125rem]">
              <p className="font-semibold">{fmt.label} – expected format</p>
              <ul className="mt-1 space-y-0.5 text-muted-foreground">
                <li>
                  <b className="font-medium text-foreground">File:</b> .xlsx or .xlsb (no macros), at most 60 MB
                </li>
                <li>
                  <b className="font-medium text-foreground">Sheet:</b> {fmt.sheet}; header {fmt.header}
                </li>
                <li>
                  <b className="font-medium text-foreground">Required columns:</b> {fmt.required}
                </li>
                {fmt.periods && (
                  <li>
                    <b className="font-medium text-foreground">Period columns:</b> {fmt.periods}
                  </li>
                )}
              </ul>
              <div className="mt-1.5 flex flex-wrap gap-3">
                {fmt.templates.map((t) => (
                  <a key={t.href} href={t.href} download className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
                    <Download className="size-3.5" aria-hidden /> {t.label}
                  </a>
                ))}
              </div>
            </div>
          ) : (
            <p className="pt-6 text-[0.78125rem] text-muted-foreground">Select the file type first – Master Data workbook or Escalation Matrix.</p>
          )}
        </div>

        {/* 2 · file */}
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border px-4 py-3">
          <input ref={input} type="file" accept={ACCEPT} className="hidden" aria-hidden tabIndex={-1} onChange={(e) => (pick(e.target.files?.[0]), (e.target.value = ""))} />
          <Button variant="outline" onClick={() => input.current?.click()} disabled={!kind || busy}>
            <FileSpreadsheet /> {file ? "Choose another file" : "Choose file"}
          </Button>
          <span className="min-w-0 flex-1 truncate text-[0.8125rem]">
            {file ? (
              <>
                <b>{file.name}</b> <span className="text-muted-foreground">· {(file.size / 1024 / 1024).toFixed(1)} MB</span>
              </>
            ) : (
              <span className="text-muted-foreground">No file chosen</span>
            )}
          </span>
          {!report && (
            <Button variant="primary" onClick={() => void validate()} disabled={!kind || !file || busy}>
              {progress !== null ? <Loader2 className="animate-spin" /> : <FileUp />} {progress === null ? "Check file" : progress < 1 ? `Uploading ${Math.round(progress * 100)}%` : "Checking…"}
            </Button>
          )}
        </div>
        {progress !== null && (
          <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
            <div className={cn("h-full bg-primary transition-[width]", progress >= 1 && "animate-pulse")} style={{ width: `${Math.max(4, progress * 100)}%` }} />
          </div>
        )}
        {error && (
          <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-[0.8125rem] text-critical-text">
            {error}
          </p>
        )}

        {/* 3 · report */}
        {report && <Report report={report} onCheckColumns={file && report.stage === "structure" ? () => onCheckColumns(file) : undefined} />}
      </div>

      <div className="flex flex-col-reverse gap-2 border-t border-border px-6 py-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-[0.75rem] text-muted-foreground">
          {report?.canImport ? `The checked file is kept for ${report.expiresInMinutes} minutes – confirm to import it.` : "Only a file that passes the checks can be imported."}
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void confirm()} disabled={!report?.canImport || busy}>
            {confirming ? <Loader2 className="animate-spin" /> : <CheckCircle2 />} Confirm import
          </Button>
        </div>
      </div>
    </DialogContent>
  );
}

function Report({ report: r, onCheckColumns }: { report: UploadPreview; onCheckColumns?: () => void }) {
  const [sev, setSev] = useState<Sev>("all");
  if (!r.canImport) {
    return (
      <div className="rounded-lg border border-critical/30 bg-critical-soft px-4 py-3 text-[0.8125rem]">
        <p className="flex items-center gap-2 font-semibold text-critical-text">
          <XCircle className="size-4" aria-hidden /> Cannot import – {STAGE_LABEL[r.stage]}
        </p>
        <p className="mt-1 text-critical-text">{r.error}</p>
        {r.templateErrors && r.templateErrors.length > 0 && (
          <div className="mt-2 max-h-64 overflow-auto rounded-md border border-critical/30 bg-card">
            <table className="w-full text-[0.75rem]">
              <thead className="sticky top-0 bg-muted">
                <tr className="text-left text-[0.6875rem] font-semibold text-muted-foreground">
                  <th className="px-2 py-1">Sheet</th>
                  <th className="px-2 py-1">Row</th>
                  <th className="px-2 py-1">Column</th>
                  <th className="px-2 py-1">Problem</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {r.templateErrors.map((e, i) => (
                  <tr key={i} className="border-t border-border/60 align-top">
                    <td className="whitespace-nowrap px-2 py-1">{e.sheet}</td>
                    <td className="px-2 py-1 font-medium">{e.row ?? "—"}</td>
                    <td className="px-2 py-1">{e.column ?? "—"}</td>
                    <td className="px-2 py-1 text-foreground">{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(r.templateErrorCount ?? 0) > r.templateErrors.length && (
              <p className="border-t border-border px-2 py-1 text-[0.71875rem] text-muted-foreground">
                First {formatCount(r.templateErrors.length)} of {formatCount(r.templateErrorCount ?? 0)} problems shown.
              </p>
            )}
          </div>
        )}
        <p className="mt-1.5 text-[0.75rem] text-muted-foreground">The file was not stored; the dashboard keeps its current data. Fix the file (or choose the right file type) and check it again.</p>
        {onCheckColumns && (
          <Button size="sm" variant="outline" className="mt-2" onClick={onCheckColumns}>
            Check the file&apos;s column names
          </Button>
        )}
      </div>
    );
  }
  const c = r.counts!;
  const issues = (r.issues ?? []).filter((i) => sev === "all" || i.severity === sev);
  const mismatches = (r.crossCheck ?? []).filter((x) => !x.match);
  return (
    <div className="space-y-3">
      <div className={cn("rounded-lg border px-4 py-2.5 text-[0.8125rem]", c.rejected ? "border-warning/40 bg-warning-soft" : "border-good/30 bg-good-soft")}>
        <p className={cn("flex items-center gap-2 font-semibold", c.rejected ? "text-warning-text" : "text-good-text")}>
          {c.rejected ? <AlertTriangle className="size-4" aria-hidden /> : <CheckCircle2 className="size-4" aria-hidden />}
          {c.rejected ? `Ready to import – ${formatCount(c.rejected)} row(s) will be skipped (listed below)` : "Ready to import – all rows passed"}
        </p>
        <p className="mt-0.5 text-[0.75rem] text-muted-foreground">
          {r.kindLabel} · {r.fileName} · SHA-256 {r.sha256.slice(0, 12)}…
        </p>
      </div>

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {(
          [
            ["Rows", c.rows, ""],
            ["Accepted", c.accepted, "text-good-text"],
            ["Rejected", c.rejected, c.rejected ? "text-critical-text" : ""],
            ["Critical", c.critical, c.critical ? "text-critical-text" : ""],
            ["Warnings", c.warning, c.warning ? "text-warning-text" : ""],
            ["Info", c.info, "text-muted-foreground"],
          ] as [string, number, string][]
        ).map(([label, v, cls]) => (
          <div key={label} className="rounded-md border border-border px-2.5 py-1.5">
            <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
            <p className={cn("tabular text-[1.0625rem] font-bold", cls)}>{formatCount(v)}</p>
          </div>
        ))}
      </div>

      {r.facts && r.facts.length > 0 && (
        <dl className="grid gap-x-6 gap-y-1 rounded-lg border border-border px-4 py-2.5 text-[0.78125rem] sm:grid-cols-2">
          {r.facts.map((f) => (
            <div key={f.label} className="flex gap-2">
              <dt className="shrink-0 text-muted-foreground">{f.label}:</dt>
              <dd className="font-medium">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {r.crossCheck && r.crossCheck.length > 0 && (
        <div className="rounded-lg border border-border">
          <p className="border-b border-border px-3 py-1.5 text-[0.78125rem] font-semibold">
            Cross-check with the file&apos;s own O&amp;M key numbers{" "}
            <span className={cn("font-normal", mismatches.length ? "text-warning-text" : "text-good-text")}>
              · {mismatches.length ? `${mismatches.length} differ (warning only)` : "all match"}
            </span>
          </p>
          <div className="max-h-40 overflow-auto">
            <table className="w-full text-[0.75rem]">
              <thead className="sticky top-0 bg-muted">
                <tr className="text-left text-[0.6875rem] font-semibold text-muted-foreground">
                  <th className="px-3 py-1">State</th>
                  <th className="px-3 py-1">Key number</th>
                  <th className="px-3 py-1 text-right">O&amp;M sheet</th>
                  <th className="px-3 py-1 text-right">Counted from rows</th>
                  <th className="px-3 py-1">Result</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {r.crossCheck.map((x) => (
                  <tr key={`${x.state}|${x.metric}`} className="border-t border-border/60">
                    <td className="px-3 py-1">{x.state}</td>
                    <td className="px-3 py-1">{x.metric}</td>
                    <td className="px-3 py-1 text-right">{formatCount(x.reported)}</td>
                    <td className="px-3 py-1 text-right">{formatCount(x.computed)}</td>
                    <td className={cn("px-3 py-1 font-semibold", x.match ? "text-good-text" : "text-warning-text")}>{x.match ? "Match" : `Differs by ${formatCount(x.difference)}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {r.columns && (r.columns.missingOptional.length > 0 || r.columns.unknown.length > 0) && (
        <div className="space-y-1 rounded-lg border border-border px-3 py-2 text-[0.75rem]">
          {r.columns.missingOptional.length > 0 && (
            <p>
              <b className="text-warning-text">Optional columns not found</b> (left empty): {r.columns.missingOptional.join(", ")}
            </p>
          )}
          {r.columns.unknown.length > 0 && (
            <p className="text-muted-foreground">
              <b className="font-medium text-foreground">Columns not used by the dashboard</b> (ignored): {r.columns.unknown.join(", ")}
            </p>
          )}
        </div>
      )}

      <div className="rounded-lg border border-border">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-1.5">
          <p className="text-[0.78125rem] font-semibold">
            Issues with their Excel row{" "}
            <span className="font-normal text-muted-foreground">
              · {formatCount(issues.length)} shown{(r.issues?.length ?? 0) < c.critical + c.warning + c.info ? ` (first ${formatCount(r.issues?.length ?? 0)} of ${formatCount(c.critical + c.warning + c.info)})` : ""}
            </span>
          </p>
          <Segmented<Sev>
            ariaLabel="Severity"
            value={sev}
            onChange={setSev}
            options={[
              { value: "all", label: "All" },
              { value: "critical", label: `Critical ${c.critical}` },
              { value: "warning", label: `Warnings ${c.warning}` },
              { value: "info", label: `Info ${c.info}` },
            ]}
          />
        </div>
        {issues.length === 0 ? (
          <p className="px-3 py-3 text-[0.78125rem] text-muted-foreground">No issues of this kind.</p>
        ) : (
          <div className="max-h-64 overflow-auto">
            <table className="w-full min-w-[40rem] text-[0.75rem]">
              <thead className="sticky top-0 bg-muted">
                <tr className="text-left text-[0.6875rem] font-semibold text-muted-foreground">
                  <th className="px-3 py-1">Row</th>
                  <th className="px-3 py-1">Severity</th>
                  <th className="px-3 py-1">Column</th>
                  <th className="px-3 py-1">GP Code</th>
                  <th className="px-3 py-1">Issue</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {issues.slice(0, 300).map((i, n) => (
                  <tr key={n} className="border-t border-border/60 align-top">
                    <td className="px-3 py-1 font-medium">{i.row ?? "—"}</td>
                    <td className={cn("px-3 py-1 font-semibold capitalize", i.severity === "critical" ? "text-critical-text" : i.severity === "warning" ? "text-warning-text" : "text-muted-foreground")}>{i.severity}</td>
                    <td className="px-3 py-1">{i.column ?? "—"}</td>
                    <td className="px-3 py-1">{i.gpCode ?? "—"}</td>
                    <td className="px-3 py-1">{i.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
