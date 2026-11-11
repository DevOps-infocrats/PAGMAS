"use client";

import { Columns3, FileDown, FileUp, Info, Loader2, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { StatusBadge } from "@/components/feedback/badges";
import { ErrorState, KpiSkeleton } from "@/components/feedback/states";
import { AdminGuard } from "@/components/layout/admin-guard";
import { PageHeader, SectionHeader } from "@/components/layout/page-header";
import { useRefresh } from "@/components/providers/data-provider";
import { DataTable, columnHelper, type Column } from "@/components/tables/data-table";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/controls";
import { Dialog } from "@/components/ui/overlays";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { IS_LIVE, adminApi, api, type EscalationImportRun, type ReconciliationRow } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate, formatDateTime, formatDuration } from "@/lib/utils/format";
import type { IngestionRun } from "@/types";
import { ColumnCheckDialog, ColumnMapperCard, type ColumnNext, type ColumnSource } from "./column-mapper";
import { PlanFilesCard } from "./plan-files-card";
import { UploadPanel, UploadToasts, jobOutcome, type UploadJob } from "./upload-progress";
import { UploadDialog } from "./upload-dialog";
import { UploadReport } from "./upload-report";

type StatusFilter = "ALL" | IngestionRun["status"];

const STATUS_TONE = { SUCCESS: "good", PARTIAL: "warning", FAILED: "critical", PROCESSING: "info" } as const;
const STATUS_LABEL = { SUCCESS: "Success", PARTIAL: "Partial", FAILED: "Failed", PROCESSING: "Processing" } as const;

export function OperationsView() {
  return (
    <AdminGuard>
      <OperationsContent />
    </AdminGuard>
  );
}

function OperationsContent() {
  const [tick, setTick] = useState(0);
  const q = useApiQuery(`ingestion-runs:${tick}`, () => api.getIngestionRuns());
  const { refresh } = useRefresh();
  const [status, setStatus] = useState<StatusFilter>("ALL");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [escTick, setEscTick] = useState(0);
  // Column check dialog (column mapper): the file / run it reads and what to do once names are added.
  const [colCheck, setColCheck] = useState<{ source: ColumnSource; fileName: string; next?: ColumnNext } | null>(null);

  const runs = q.data ?? q.staleData;
  const processing = runs?.some((r) => r.status === "PROCESSING");

  // Poll while an import is running; refresh all dashboards once it finishes.
  const wasProcessing = useRef(false);
  useEffect(() => {
    if (processing) {
      wasProcessing.current = true;
      const t = setTimeout(() => setTick((n) => n + 1), 3000);
      return () => clearTimeout(t);
    }
    if (wasProcessing.current) {
      wasProcessing.current = false;
      refresh();
    }
  }, [processing, runs, refresh]);

  // Escalation Matrix imports (also polled while one is processing).
  const [escPoll, setEscPoll] = useState(0);
  const escQ = useApiQuery(IS_LIVE ? `escalation-imports:${escTick}:${escPoll}` : null, () => adminApi.getEscalationImports());
  const escList = escQ.data ?? escQ.staleData;
  const escProcessing = escList?.some((x) => x.status === "PROCESSING");
  const escWasProcessing = useRef(false);
  useEffect(() => {
    if (escProcessing) {
      escWasProcessing.current = true;
      const t = setTimeout(() => setEscPoll((n) => n + 1), 3000);
      return () => clearTimeout(t);
    }
    if (escWasProcessing.current) {
      escWasProcessing.current = false;
      refresh();
    }
  }, [escProcessing, escList, refresh]);

  // Files uploaded from this page: where each one stands is read from the two lists above.
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const [now, setNow] = useState(0);
  const [toastsSeen, setToastsSeen] = useState<string[]>([]);
  const outcomes = jobs.map((job) => ({ job, outcome: jobOutcome(job, runs, escList) }));
  const jobsBusy = outcomes.some((x) => x.outcome.state !== "done");
  useEffect(() => {
    if (!jobsBusy) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [jobsBusy]);
  const toasts = outcomes.flatMap(({ job, outcome }) =>
    outcome.state === "done" && !toastsSeen.includes(job.key) ? [{ key: job.key, name: job.name, tone: outcome.tone, title: outcome.title }] : [],
  );
  const toastKeys = toasts.map((t) => t.key).join("|");
  useEffect(() => {
    if (!toastKeys) return;
    const t = setTimeout(() => setToastsSeen((seen) => [...seen, ...toastKeys.split("|")]), 8000);
    return () => clearTimeout(t);
  }, [toastKeys]);
  const newRunIds = jobs.flatMap((j) => (j.kind === "master" && j.runId ? [j.runId] : [])).join(",");

  // Upload = choose the file type, check the file (preview report), confirm; then its import is followed here.
  const [uploadOpen, setUploadOpen] = useState(false);
  const onConfirmed = (r: { id: string; kind: "master" | "escalation"; fileName: string; size: number }) => {
    const t0 = Date.now();
    setUploadOpen(false);
    setJobs([{ key: `${t0}`, name: r.fileName, size: r.size, phase: "accepted", progress: 1, kind: r.kind, runId: r.id.replace(/^esc-/, ""), processingSince: t0 }]);
    setToastsSeen([]);
    setNow(t0);
    setMessage(null);
    if (r.kind === "escalation") setEscTick((n) => n + 1);
    else setTick((n) => n + 1);
  };

  const showRun = (id: string) => {
    setStatus("ALL");
    setSelectedId(id);
    requestAnimationFrame(() => (document.getElementById("ops-report") ?? document.getElementById("ops-history"))?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  const checkFile = (file: File) =>
    setColCheck({
      source: { file },
      fileName: file.name,
      next: {
        label: "Upload a file",
        run: () => {
          setColCheck(null);
          setUploadOpen(true);
        },
      },
    });

  const latest = runs?.[0];
  const active = runs?.find((r) => r.isActive) ?? runs?.find((r) => r.status === "SUCCESS");
  const filtered = useMemo(() => (runs ?? []).filter((r) => status === "ALL" || r.status === status), [runs, status]);
  const selected = runs?.find((r) => r.id === selectedId) ?? latest;

  const columns = useMemo<Column<IngestionRun>[]>(() => {
    const h = columnHelper<IngestionRun>();
    const retry = async (id: string, reprocess = false) => {
      setRetrying(id);
      try {
        const res = reprocess ? await adminApi.reprocessRun(id) : await api.retryIngestion(id);
        setMessage({ tone: res.accepted ? "info" : "error", text: res.message });
        setTick((n) => n + 1);
      } catch (e) {
        setMessage({ tone: "error", text: e instanceof Error ? e.message : "Retry failed" });
      } finally {
        setRetrying(null);
      }
    };
    return [
      h.accessor("fileName", {
        header: "File",
        cell: (c) => (
          <span className="font-medium">
            {c.getValue()}
            {c.row.original.isActive && <span className="ml-2 rounded bg-good-soft px-1.5 py-0.5 text-[0.6875rem] text-good-text">Active</span>}
            {newRunIds.split(",").includes(c.row.original.id) && (
              <span className="ml-2 rounded bg-primary-soft px-1.5 py-0.5 text-[0.6875rem] text-primary">Just uploaded</span>
            )}
          </span>
        ),
      }),
      h.accessor("startedAt", { header: "Started", cell: (c) => (c.getValue() ? formatDateTime(c.getValue() as string) : "—") }),
      h.accessor("status", { header: "Status", cell: (c) => <RunStatus status={c.row.original.status} /> }),
      h.accessor((r) => r.dataAsOf ?? "", { id: "dataAsOf", header: "Data as of", cell: (c) => formatDate(c.row.original.dataAsOf ?? null) }),
      h.accessor("accepted", { header: "Accepted", cell: (c) => formatCount(c.getValue()) }),
      h.accessor("rejected", { header: "Rejected", cell: (c) => formatCount(c.getValue()) }),
      h.accessor("durationSec", { header: "Duration", cell: (c) => formatDuration(c.getValue()) }),
      h.display({
        id: "actions",
        header: "",
        cell: (c) => {
          const r = c.row.original;
          const check =
            IS_LIVE && (r.status === "FAILED" || (r.missingColumns ?? 0) > 0) ? (
              <Button
                size="sm"
                variant="outline"
                title="Which sheets / columns of this file the importer did not recognise"
                onClick={(e) => {
                  e.stopPropagation();
                  setColCheck({
                    source: { runId: r.id },
                    fileName: r.fileName,
                    next:
                      r.status === "FAILED"
                        ? { label: "Retry import", run: () => { setColCheck(null); return retry(r.id); } }
                        : r.status === "SUCCESS" || r.status === "PARTIAL"
                          ? { label: "Re-process import", run: () => { setColCheck(null); return retry(r.id, true); } }
                          : undefined,
                  });
                }}
              >
                <Columns3 /> Columns
              </Button>
            ) : null;
          return (
            <div className="flex justify-end gap-1.5">
              {check}
              {r.status === "FAILED" || r.status === "PARTIAL" ? (
            <Button
              size="sm"
              variant="outline"
              onClick={(e) => {
                e.stopPropagation();
                void retry(c.row.original.id);
              }}
              disabled={retrying === c.row.original.id}
            >
              {retrying === c.row.original.id ? <Loader2 className="animate-spin" /> : <RotateCcw />}
              Retry{IS_LIVE ? "" : " (demo)"}
            </Button>
              ) : null}
            </div>
          );
        },
      }),
    ];
  }, [retrying, newRunIds]);

  return (
    <div className="space-y-8">
      <PageHeader
        breadcrumbs={[{ label: "Administration" }, { label: "Data Operations" }]}
        title="Data Operations"
        description="Import the master data workbook or the Escalation Matrix (choose the file type, check the file, confirm), monitor processing and check data accuracy."
        actions={
          IS_LIVE ? (
            <Button variant="primary" onClick={() => setUploadOpen(true)} disabled={jobsBusy} title={jobsBusy ? "Please wait until the current import finishes" : undefined}>
              {jobsBusy ? <Loader2 className="animate-spin" /> : <FileUp />}
              {jobsBusy ? "Processing…" : "Upload data file"}
            </Button>
          ) : null
        }
      />

      {!IS_LIVE && (
        <div role="note" className="flex items-start gap-3 rounded-lg border border-border bg-primary-soft/50 px-4 py-3 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-primary" />
          <p>Demo mode: these runs are generated placeholders. Start the backend and use NEXT_PUBLIC_API_MODE=live to import real files.</p>
        </div>
      )}

      {IS_LIVE && (
        <UploadPanel jobs={jobs} runs={runs} escalation={escList} now={now} onClear={() => setJobs([])} onShowRun={showRun} onCheckColumns={(job) => job.file && checkFile(job.file)} />
      )}

      {message && (
        <p
          role="status"
          className={`rounded-md border px-4 py-2.5 text-sm ${message.tone === "error" ? "border-critical/30 bg-critical-soft text-critical-text" : "border-border bg-card text-muted-foreground"}`}
        >
          {message.text}
        </p>
      )}

      {q.error && !runs ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <Card>
          <div className="grid grid-cols-1 divide-y divide-border sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4">
            {!runs
              ? Array.from({ length: 4 }, (_, i) => <KpiSkeleton key={i} />)
              : [
                  { label: "Active dataset", value: active?.fileName ?? "None", small: true },
                  { label: "Data as of", value: formatDate(active?.dataAsOf ?? null) },
                  { label: "Latest import status", value: latest ? <StatusBadge tone={STATUS_TONE[latest.status]}>{STATUS_LABEL[latest.status]}</StatusBadge> : "—" },
                  { label: "Processing duration", value: formatDuration(latest?.durationSec ?? null) },
                  { label: "Records accepted", value: formatCount(latest?.accepted) },
                  { label: "Records rejected", value: formatCount(latest?.rejected) },
                  { label: "Critical issues", value: formatCount(latest?.issueCounts?.critical ?? latest?.validationErrors.length) },
                  { label: "Warnings", value: formatCount(latest?.issueCounts?.warning ?? null) },
                ].map((s, i) => (
                  <div key={s.label} className={`space-y-1.5 p-5 ${i >= 4 ? "lg:border-t lg:border-border" : ""} ${i % 4 ? "lg:border-l lg:border-border" : ""}`}>
                    <p className="text-[0.8125rem] text-muted-foreground">{s.label}</p>
                    <div className={s.small ? "break-all text-sm font-medium" : "text-lg font-semibold"}>{s.value}</div>
                  </div>
                ))}
          </div>
          {latest?.status === "FAILED" && latest.message && <p className="border-t border-border px-5 py-3 text-sm text-critical-text">{latest.message}</p>}
        </Card>
      )}

      {IS_LIVE && (
        <EscalationImports
          list={escList}
          error={escQ.error}
          onRetry={escQ.reload}
          onCheckColumns={(x) =>
            setColCheck({
              source: { escalationId: x.id },
              fileName: x.fileName,
              next:
                x.status === "SUCCESS"
                  ? {
                      label: "Re-process import",
                      run: async () => {
                        setColCheck(null);
                        try {
                          const res = await adminApi.reprocessEscalation(x.id);
                          setMessage({ tone: "info", text: res.message });
                        } catch (e) {
                          setMessage({ tone: "error", text: e instanceof Error ? e.message : "Re-process failed" });
                        }
                        setEscTick((n) => n + 1);
                      },
                    }
                  : undefined,
            })
          }
        />
      )}

      {IS_LIVE && <ColumnMapperCard onCheckFile={checkFile} />}

      {IS_LIVE && <Reconciliation key={active?.id ?? "none"} />}

      {IS_LIVE && <PlanFilesCard />}

      <section className="space-y-4" aria-labelledby="ops-history">
        <SectionHeader id="ops-history" title="Import history" description="Select a run to see what changed in that upload and its data-quality issues." />
        <Card className="overflow-hidden">
          <DataTable
            data={runs ? filtered : undefined}
            columns={columns}
            loading={!runs}
            numericColumns={["accepted", "rejected", "durationSec"]}
            searchPlaceholder="Search file names…"
            onRowClick={(r) => setSelectedId(r.id)}
            rowLabel={(r) => `Show data-quality issues for ${r.fileName}`}
            toolbar={
              <Segmented<StatusFilter>
                ariaLabel="Filter by status"
                value={status}
                onChange={setStatus}
                options={[
                  { value: "ALL", label: "All" },
                  { value: "SUCCESS", label: "Success" },
                  { value: "PARTIAL", label: "Partial" },
                  { value: "FAILED", label: "Failed" },
                ]}
              />
            }
          />
        </Card>
      </section>

      {selected && IS_LIVE && <UploadReport key={`report-${selected.id}`} run={selected} />}
      {selected && (IS_LIVE ? <RunIssues key={`issues-${selected.id}`} run={selected} /> : <DemoIssues run={selected} />)}

      <UploadToasts items={toasts} onClose={(key) => setToastsSeen((seen) => [...seen, key])} />

      <Dialog open={uploadOpen} onOpenChange={(o) => !o && setUploadOpen(false)}>
        {uploadOpen && (
          <UploadDialog
            onConfirmed={onConfirmed}
            onClose={() => setUploadOpen(false)}
            onCheckColumns={(file) => {
              setUploadOpen(false);
              checkFile(file);
            }}
          />
        )}
      </Dialog>

      <Dialog open={colCheck != null} onOpenChange={(o) => !o && setColCheck(null)}>
        {colCheck && <ColumnCheckDialog source={colCheck.source} fileName={colCheck.fileName} next={colCheck.next} />}
      </Dialog>
    </div>
  );
}

/** Status badge; the icon turns while an import is processing. */
function RunStatus({ status }: { status: keyof typeof STATUS_TONE }) {
  return (
    <StatusBadge tone={STATUS_TONE[status]} className={status === "PROCESSING" ? "[&>svg]:animate-spin" : undefined}>
      {STATUS_LABEL[status]}
    </StatusBadge>
  );
}

/** Escalation Matrix uploads: status of each; the active one feeds Field Team & Escalation (polled by the page). */
function EscalationImports({
  list,
  error,
  onRetry,
  onCheckColumns,
}: {
  list: EscalationImportRun[] | undefined;
  error?: Error;
  onRetry: () => void;
  onCheckColumns: (x: EscalationImportRun) => void;
}) {
  const active = list?.find((x) => x.isActive);
  return (
    <section className="space-y-4" aria-labelledby="ops-escalation">
      <SectionHeader
        id="ops-escalation"
        title="Escalation Matrix"
        description="GP-wise field team and escalation contacts – used by Field Team & Escalation. Upload it with “Upload data file” above (file type: Escalation Matrix)."
      />
      <Card className="overflow-hidden">
        {error && !list ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : !list ? (
          <div className="p-5">
            <KpiSkeleton />
          </div>
        ) : list.length === 0 ? (
          <p className="px-5 py-4 text-sm text-muted-foreground">No Escalation Matrix uploaded yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-sm">
              <caption className="sr-only">Escalation Matrix uploads</caption>
              <thead>
                <tr className="border-b border-border bg-card text-left text-[0.78125rem] font-semibold text-foreground">
                  <th scope="col" className="px-4 py-2.5">
                    File
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Started
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    Status
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right">
                    GPs
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right">
                    Rejected
                  </th>
                  <th scope="col" className="px-4 py-2.5 text-right">
                    Duration
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.map((x) => (
                  <tr key={x.id} className="border-b border-border/70 last:border-0">
                    <td className="px-4 py-2.5 font-medium">
                      {x.fileName}
                      {x.isActive && <span className="ml-2 rounded bg-good-soft px-1.5 py-0.5 text-[0.6875rem] text-good-text">Active</span>}
                      {x.message && (x.status === "FAILED" || x.columnsMissing || x.message.startsWith("Re-process")) && (
                        <span className={`block text-xs font-normal ${x.status === "FAILED" ? "text-critical-text" : "text-warning-text"}`}>{x.message}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">{x.startedAt ? formatDateTime(x.startedAt) : "—"}</td>
                    <td className="px-4 py-2.5">
                      <RunStatus status={x.status} />
                    </td>
                    <td className="tabular px-4 py-2.5 text-right">{formatCount(x.rows)}</td>
                    <td className="tabular px-4 py-2.5 text-right">{formatCount(x.rejected)}</td>
                    <td className="tabular px-4 py-2.5 text-right">{formatDuration(x.durationSec)}</td>
                    <td className="px-4 py-2.5 text-right">
                      {(x.columnsMissing || x.status === "FAILED") && (
                        <Button size="sm" variant="outline" onClick={() => onCheckColumns(x)} title="Which columns of this file the importer did not recognise">
                          <Columns3 /> Columns
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {active && (
        <p className="text-xs text-muted-foreground">
          Active: {active.fileName} – {formatCount(active.rows)} GPs.
        </p>
      )}
    </section>
  );
}

const RECON_TONE = { MATCH: "good", EXPLAINED: "info", MISMATCH: "critical", NO_REFERENCE: "neutral" } as const;
const RECON_LABEL = { MATCH: "Match", EXPLAINED: "Explained", MISMATCH: "Mismatch", NO_REFERENCE: "No reference" } as const;

function Reconciliation() {
  const q = useApiQuery("reconciliation", () => adminApi.getReconciliation());
  const columns = useMemo<Column<ReconciliationRow>[]>(() => {
    const h = columnHelper<ReconciliationRow>();
    const num = (v: number | null) => (v == null ? "NA" : Number.isInteger(v) ? formatCount(v) : v.toLocaleString("en-IN", { maximumFractionDigits: 2 }));
    return [
      h.accessor("state", { header: "State" }),
      h.accessor("metric", { header: "Metric (O&M sheet)", cell: (c) => <span className="font-medium">{c.getValue()}</span> }),
      h.accessor("reported", { header: "O&M value", cell: (c) => num(c.getValue()) }),
      h.accessor("computed", { header: "Dashboard", cell: (c) => num(c.getValue()) }),
      h.accessor("status", { header: "Result", cell: (c) => <StatusBadge tone={RECON_TONE[c.row.original.status]}>{RECON_LABEL[c.row.original.status]}</StatusBadge> }),
      h.accessor((r) => r.note ?? "", {
        id: "note",
        header: "Explanation",
        cell: (c) => <span className="block max-w-md whitespace-normal text-xs text-muted-foreground">{c.row.original.note ?? "—"}</span>,
      }),
    ];
  }, []);
  const rows = q.data?.rows;
  const counts = rows?.reduce<Record<string, number>>((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <section className="space-y-4" aria-labelledby="ops-recon">
      <SectionHeader
        id="ops-recon"
        title="Accuracy check (reconciliation)"
        description={
          q.data
            ? `Dashboard figures vs the O&M sheet's KEY NUMBERS · ${counts?.MATCH ?? 0} match, ${counts?.EXPLAINED ?? 0} explained, ${counts?.MISMATCH ?? 0} unexplained`
            : "Dashboard figures vs the O&M sheet's KEY NUMBERS"
        }
      />
      <Card className="overflow-hidden">
        <DataTable
          data={rows}
          columns={columns}
          loading={q.loading}
          error={q.error}
          onRetry={q.reload}
          numericColumns={["reported", "computed"]}
          searchPlaceholder="Search metrics or states…"
          pageSize={25}
          exportName="reconciliation"
        />
      </Card>
    </section>
  );
}

type Severity = "all" | "critical" | "warning" | "info";

function RunIssues({ run }: { run: IngestionRun }) {
  const [severity, setSeverity] = useState<Severity>("all");
  const [code, setCode] = useState<string | null>(null);
  const filters = { severity: severity === "all" ? undefined : severity, code: code ?? undefined };
  const q = useApiQuery(`issues:${run.id}:${severity}:${code}:${run.status}`, () => adminApi.getRunIssues(run.id, filters));
  return (
    <section className="space-y-4" aria-labelledby="ops-errors">
      <SectionHeader
        id="ops-errors"
        title="Data-quality issues"
        description={`${run.fileName} · ${formatCount(q.data?.total ?? null)} issues${severity === "all" ? "" : ` (${severity})`}${code ? ` · ${code.replaceAll("_", " ").toLowerCase()}` : ""}`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Segmented<Severity>
              ariaLabel="Severity"
              value={severity}
              onChange={setSeverity}
              options={[
                { value: "all", label: "All" },
                { value: "critical", label: "Critical" },
                { value: "warning", label: "Warning" },
                { value: "info", label: "Info" },
              ]}
            />
            <Button asChild variant="outline" size="sm">
              <a href={adminApi.runIssuesXlsxUrl(run.id, filters)} download>
                <FileDown /> Excel
              </a>
            </Button>
          </div>
        }
      />
      <Card className="p-5">
        {q.error ? (
          <ErrorState error={q.error} onRetry={q.reload} />
        ) : !q.data ? (
          <KpiSkeleton />
        ) : (
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2">
              {q.data.summary.map((s) => (
                <button
                  key={`${s.code}-${s.severity}`}
                  type="button"
                  aria-pressed={code === s.code}
                  title={code === s.code ? "Show all codes" : `Show only ${s.code.replaceAll("_", " ").toLowerCase()}`}
                  className={cn("rounded-full transition-shadow", code === s.code && "ring-2 ring-primary/50 ring-offset-1 ring-offset-card")}
                  onClick={() => setCode((c) => (c === s.code ? null : s.code))}
                >
                  <StatusBadge tone={s.severity === "critical" ? "critical" : s.severity === "warning" ? "warning" : "neutral"}>
                    {s.code.replaceAll("_", " ").toLowerCase()} · {formatCount(s.count)}
                  </StatusBadge>
                </button>
              ))}
              {!q.data.summary.length && <p className="text-sm text-muted-foreground">No issues recorded for this import.</p>}
            </div>
            {q.data.summary.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Click a code to see only those rows. These are problems in the source workbook: the dashboard keeps such values blank (never 0) – download the Excel and send it to the team that maintains the file.
              </p>
            )}
            {q.data.items.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[40rem] text-[0.8125rem]">
                  <thead>
                    <tr className="border-b border-border text-left text-muted-foreground">
                      {["Excel row", "GP code", "Column", "Severity", "Message"].map((c) => (
                        <th key={c} scope="col" className="py-2 pr-3 font-medium">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {q.data.items.map((e, i) => (
                      <tr key={i} className="border-b border-border/60 last:border-0">
                        <td className="tabular py-2 pr-3">{e.row ?? "—"}</td>
                        <td className="tabular py-2 pr-3">{e.gpCode ?? "—"}</td>
                        <td className="py-2 pr-3">{e.column ?? "—"}</td>
                        <td className="py-2 pr-3 capitalize">{e.severity}</td>
                        <td className="py-2">{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {q.data.total > q.data.items.length && (
                  <p className="pt-3 text-xs text-muted-foreground">
                    Showing the first {q.data.items.length} of {formatCount(q.data.total)}.
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </Card>
    </section>
  );
}

function DemoIssues({ run }: { run: IngestionRun }) {
  return (
    <section className="space-y-4">
      <SectionHeader title="Validation errors" description={run.fileName} />
      <Card className="p-5">
        {run.validationErrors.length ? (
          <ul className="space-y-2 text-sm">
            {run.validationErrors.map((e, i) => (
              <li key={i}>
                Row {e.row} · {e.column}: {e.message}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No validation errors recorded for this run.</p>
        )}
      </Card>
    </section>
  );
}
