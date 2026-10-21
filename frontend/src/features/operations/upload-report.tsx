"use client";

import { AlertTriangle, ArrowRight, FileSearch } from "lucide-react";
import { StatusBadge } from "@/components/feedback/badges";
import { EmptyState, ErrorState, KpiSkeleton } from "@/components/feedback/states";
import { SectionHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { adminApi, type UploadReport as Report, type UploadReportGp } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate } from "@/lib/utils/format";
import type { IngestionRun } from "@/types";

const signed = (n: number | null | undefined) => (n == null ? "—" : n > 0 ? `+${formatCount(n)}` : n < 0 ? `−${formatCount(-n)}` : "±0");

/** "What changed in this upload" – the report built during the import, compared with the previous upload. */
export function UploadReport({ run }: { run: IngestionRun }) {
  const q = useApiQuery(run.hasReport ? `upload-report:${run.id}:${run.status}` : null, () => adminApi.getRunReport(run.id));
  const r = q.data;
  return (
    <section className="space-y-4" aria-labelledby="ops-report">
      <SectionHeader
        id="ops-report"
        title="Upload report – what changed"
        description={
          r?.previous ? `${r.fileName} compared with the previous upload ${r.previous.fileName}` : r ? `${r.fileName} · first upload with a report – nothing to compare with yet` : run.fileName
        }
      />
      {!run.hasReport ? (
        <Card>
          <EmptyState
            icon={FileSearch}
            title="No report for this upload"
            description={run.status === "FAILED" ? "The import failed, so no data was compared." : "This file was imported before upload reports existed. The next upload will have one."}
          />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !r ? (
        <Card className="p-5">
          <KpiSkeleton />
        </Card>
      ) : r.error ? (
        <Card className="p-5 text-sm text-muted-foreground">{r.error}</Card>
      ) : (
        <ReportBody r={r} />
      )}
    </section>
  );
}

function ReportBody({ r }: { r: Report }) {
  const g = r.gps;
  const compared = !!r.previous;
  return (
    <div className="space-y-4">
      {r.notes.length > 0 && (
        <div role="alert" className="space-y-1.5 rounded-lg border border-warning/50 bg-warning-soft px-4 py-3 text-sm text-warning-text">
          <p className="flex items-center gap-2 font-semibold">
            <AlertTriangle className="size-4" aria-hidden /> Please check
          </p>
          <ul className="list-disc space-y-1 pl-6">
            {r.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      )}

      <Card className="grid grid-cols-1 divide-y divide-border p-0 sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4">
        <Tile label="Data as of" value={formatDate(r.dataAsOf.current)} sub={compared ? `previous ${formatDate(r.dataAsOf.previous)} · ${r.dataAsOf.newDays == null ? "—" : `${signed(r.dataAsOf.newDays)} day(s)`}` : undefined} />
        <Tile label="GPs in the file" value={formatCount(g.current)} sub={compared ? `${signed(g.current - (g.previous ?? 0))} · ${formatCount(g.added)} added · ${formatCount(g.removed)} removed` : undefined} />
        <Tile label="Newly HOTO done / under AMC" value={compared ? `${formatCount(g.hotoNew)} / ${formatCount(g.amcNew)}` : "—"} sub={compared ? "GPs that had no HOTO / AMC date before" : "compared from the next upload"} />
        <Tile label="Dates corrected" value={compared ? `${formatCount(g.amcDateChanged)} AMC · ${formatCount(g.hotoDateChanged)} HOTO` : "—"} sub={compared ? "existing dates that changed" : undefined} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="space-y-3 p-5">
          <h3 className="text-[15px] font-semibold">Columns & sheets</h3>
          <Changes label="New columns" items={r.columns.added} tone="good" compared={r.columns.compared} empty="none" />
          <Changes label="Columns missing (were in the previous file)" items={r.columns.removed} tone="critical" compared={r.columns.compared} empty="none" />
          <Changes label="Optional fields not found (shown as NA)" items={r.columns.missingOptional} tone="warning" compared empty="none – every field was found" />
          <Changes label="New sheets" items={r.sheets.added} tone="good" compared={r.sheets.compared} empty="none" />
          <Changes label="Sheets missing" items={r.sheets.removed} tone="critical" compared={r.sheets.compared} empty="none" />
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">{formatCount(r.columns.notUsed.length)} columns in the file are not used by the dashboard</summary>
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{r.columns.notUsed.join(" · ") || "—"}</p>
          </details>
        </Card>

        <Card className="space-y-3 p-5">
          <h3 className="text-[15px] font-semibold">Weeks, states & data quality</h3>
          <Changes label="New weeks" items={r.weeks.added} tone="good" compared={r.weeks.compared} empty="none" />
          <p className="text-sm text-muted-foreground">Weeks in the file: {r.weeks.current.join(", ") || "—"}</p>
          <table className="w-full text-[13px]">
            <caption className="sr-only">GPs per state</caption>
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th scope="col" className="py-1.5 font-medium">State</th>
                <th scope="col" className="py-1.5 text-right font-medium">Previous</th>
                <th scope="col" className="py-1.5 text-right font-medium">Now</th>
                <th scope="col" className="py-1.5 text-right font-medium">Change</th>
              </tr>
            </thead>
            <tbody className="tabular">
              {g.byCircle.map((c) => (
                <tr key={c.circle} className="border-b border-border/60 last:border-0">
                  <th scope="row" className="py-1.5 text-left font-medium">{c.circle}</th>
                  <td className="py-1.5 text-right text-muted-foreground">{c.previous == null ? "—" : formatCount(c.previous)}</td>
                  <td className="py-1.5 text-right font-semibold">{formatCount(c.current)}</td>
                  <td className="py-1.5 text-right">{c.previous == null ? "—" : signed(c.current - c.previous)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-sm">
            Data-quality issues:{" "}
            {(["critical", "warning", "info"] as const).map((s) => (
              <span key={s} className="mr-3 inline-block">
                <span className="capitalize text-muted-foreground">{s}</span> <b className="tabular">{formatCount(r.issues.current[s])}</b>
                {r.issues.previous && <span className="text-xs text-muted-foreground"> ({signed(r.issues.current[s] - r.issues.previous[s])})</span>}
              </span>
            ))}
          </p>
        </Card>
      </div>

      {compared && (g.added > 0 || g.removed > 0 || g.amcDateChanged > 0 || g.hotoDateChanged > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {g.added > 0 && <GpList title={`GPs added (${formatCount(g.added)})`} rows={g.addedSample} total={g.added} />}
          {g.removed > 0 && <GpList title={`GPs removed (${formatCount(g.removed)})`} rows={g.removedSample} total={g.removed} />}
          {g.amcDateChanged > 0 && <GpList title={`AMC date changed (${formatCount(g.amcDateChanged)})`} rows={g.amcDateChangedSample} total={g.amcDateChanged} dates />}
          {g.hotoDateChanged > 0 && <GpList title={`HOTO date changed (${formatCount(g.hotoDateChanged)})`} rows={g.hotoDateChangedSample} total={g.hotoDateChanged} dates />}
        </div>
      )}
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="space-y-1 p-5 lg:border-l lg:border-border lg:first:border-l-0">
      <p className="text-[13px] text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold tabular">{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function Changes({ label, items, tone, compared, empty }: { label: string; items: string[]; tone: "good" | "critical" | "warning"; compared: boolean; empty: string }) {
  return (
    <div className="text-sm">
      <p className="text-muted-foreground">{label}</p>
      {!compared ? (
        <p className="text-xs text-subtle-foreground">compared from the next upload</p>
      ) : items.length ? (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {items.map((x) => (
            <StatusBadge key={x} tone={tone}>
              {x}
            </StatusBadge>
          ))}
        </div>
      ) : (
        <p className="text-xs text-subtle-foreground">{empty}</p>
      )}
    </div>
  );
}

function GpList({ title, rows, total, dates }: { title: string; rows: (UploadReportGp & { from?: string | null; to?: string | null })[]; total: number; dates?: boolean }) {
  return (
    <Card className="space-y-2 p-5">
      <h3 className="text-[15px] font-semibold">{title}</h3>
      <table className="w-full text-[13px]">
        <caption className="sr-only">{title}</caption>
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th scope="col" className="py-1.5 font-medium">GP</th>
            <th scope="col" className="py-1.5 font-medium">Code</th>
            <th scope="col" className="py-1.5 font-medium">State</th>
            {dates && <th scope="col" className="py-1.5 font-medium">Date</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((x) => (
            <tr key={x.code} className="border-b border-border/60 last:border-0">
              <td className="py-1.5 font-medium">{x.name}</td>
              <td className="py-1.5 tabular text-muted-foreground">{x.code}</td>
              <td className="py-1.5">{x.circle}</td>
              {dates && (
                <td className="whitespace-nowrap py-1.5 tabular">
                  {formatDate(x.from ?? null)} <ArrowRight className="inline size-3 text-muted-foreground" aria-hidden /> <span className={cn(!x.to && "text-critical-text")}>{x.to ? formatDate(x.to) : "removed"}</span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {total > rows.length && <p className="text-xs text-muted-foreground">Showing {rows.length} of {formatCount(total)}.</p>}
    </Card>
  );
}
