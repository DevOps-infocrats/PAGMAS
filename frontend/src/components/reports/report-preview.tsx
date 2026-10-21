import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { StatusBadge } from "@/components/feedback/badges";
import type { ReportComparisonRow, WeeklyReportResponse } from "@/lib/api";
import { changeText, executiveSummary } from "@/lib/reports/report-service";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate, formatDateTime, formatPercent, formatRelativeChange, formatValue } from "@/lib/utils/format";

/** A4-style preview of the weekly management report (watermarked in demo mode). */
export function ReportPreview({ report }: { report: WeeklyReportResponse }) {
  const amcRow = report.comparison.find((c) => c.key === "amcPct");
  const availRow = report.comparison.find((c) => c.key === "availability");
  return (
    <article id="report-print-area" className="relative mx-auto w-full max-w-[860px] overflow-hidden rounded-lg border border-border bg-card shadow-sm">
      {report.isDemo && (
        <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-hidden">
          <span className="-rotate-[30deg] select-none whitespace-nowrap text-[64px] font-black tracking-widest text-foreground/[0.04] sm:text-[88px]">
            DEMO · NOT VERIFIED
          </span>
        </div>
      )}

      <div className="relative space-y-8 p-6 sm:p-10">
        <header className="flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <Logo variant="wordmark" width={110} />
            <h2 className="text-xl font-semibold tracking-tight">Weekly network performance report</h2>
            <p className="text-sm text-muted-foreground">
              {report.scopeLabel} · {report.week.label} ({formatDate(report.week.startDate)} – {formatDate(report.week.endDate)}) vs {report.compareWeek.label}
            </p>
          </div>
          <div className="space-y-2 text-left sm:text-right">
            {report.isDemo ? (
              <StatusBadge tone="warning">DEMO – not a verified report</StatusBadge>
            ) : (
              <StatusBadge tone="good">Data as of {formatDate(report.dataAsOf ?? null)}</StatusBadge>
            )}
            <p className="text-xs text-subtle-foreground">Generated {formatDateTime(report.generatedAt)}</p>
          </div>
        </header>

        <ReportSection title="1. Executive summary">
          <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed">
            {executiveSummary(report).map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </ReportSection>

        <ReportSection title="2. KPI comparison">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-[13px]">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th scope="col" className="py-2 pr-2 font-medium">Metric</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium">{report.compareWeek.label}</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium">{report.week.label}</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium">Change</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium">% / pp</th>
                  <th scope="col" className="py-2 pl-2 text-right font-medium">Trend</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {report.comparison.map((r) => (
                  <tr key={r.key} className="border-b border-border/60">
                    <td className="py-2 pr-2">{r.label}</td>
                    <td className="px-2 py-2 text-right">{formatValue(r.previous, r.unit)}</td>
                    <td className="px-2 py-2 text-right font-medium">{formatValue(r.current, r.unit)}</td>
                    <td className="px-2 py-2 text-right">{changeText(r)}</td>
                    <td className="px-2 py-2 text-right">{r.unit === "percent" ? changeText(r) : formatRelativeChange(r.current, r.previous)}</td>
                    <td className="py-2 pl-2 text-right">
                      <Trend row={r} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-subtle-foreground">Percentage metrics are compared in percentage points (pp); counts and RKM use relative % change.</p>
        </ReportSection>

        <ReportSection title="3. Performance ranking">
          <ol className="divide-y divide-border/60 text-sm">
            {report.ranking.slice(0, 10).map((r, i) => (
              <li key={r.id} className="flex items-center gap-3 py-2">
                <span className="tabular w-6 text-subtle-foreground">{i + 1}</span>
                <span className="flex-1 font-medium">{r.name}</span>
                <span className="tabular w-20 text-right">{formatPercent(r.availability, 2)}</span>
                <span className="hidden w-28 text-right text-xs text-muted-foreground sm:inline">AMC {formatPercent(r.amcPct)}</span>
              </li>
            ))}
          </ol>
        </ReportSection>

        <div className="grid gap-8 md:grid-cols-2">
          <ReportSection title="4. HOTO progress">
            {report.hotoProgress.map((h) => {
              const total = h.done + h.pending;
              const pct = total ? (h.done / total) * 100 : 0;
              return (
                <div key={h.label} className="mb-3 space-y-1">
                  <div className="flex justify-between text-sm">
                    <span>{h.label}</span>
                    <span className="tabular">
                      {formatCount(h.done)} done · {formatCount(h.pending)} pending
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </ReportSection>
          <ReportSection title="5. AMC coverage & availability">
            <dl className="space-y-2 text-sm">
              {[amcRow, availRow].map(
                (r) =>
                  r && (
                    <div key={r.key} className="flex justify-between">
                      <dt className="text-muted-foreground">{r.label}</dt>
                      <dd className="tabular font-medium">
                        {formatValue(r.current, r.unit)} <span className="text-xs font-normal text-muted-foreground">({changeText(r)})</span>
                      </dd>
                    </div>
                  ),
              )}
            </dl>
          </ReportSection>
        </div>

        <ReportSection title="6. Fibre route & incremental GPs">
          <table className="w-full text-[13px]">
            <tbody className="tabular">
              {report.fibreChanges.map((f) => (
                <tr key={f.label} className="border-b border-border/60">
                  <td className="py-2">{f.label}</td>
                  <td className="py-2 text-right text-muted-foreground">{formatCount(f.previous == null ? null : Math.round(f.previous))}</td>
                  <td className="py-2 text-right font-medium">{formatCount(f.current == null ? null : Math.round(f.current))}</td>
                  <td className="py-2 text-right">{formatRelativeChange(f.current, f.previous)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ReportSection>

        <div className="grid gap-8 md:grid-cols-2">
          <ReportSection title="7. Penalty-prone blocks">
            {report.penaltyBlocks.length ? (
              <ul className="space-y-1.5 text-sm">
                {report.penaltyBlocks.map((b) => (
                  <li key={b.id} className="flex justify-between gap-3">
                    <span className="truncate">
                      {b.name} <span className="text-xs text-muted-foreground">· {b.districtName}</span>
                    </span>
                    <span className="tabular shrink-0 font-medium text-critical-text">{formatPercent(b.availability, 2)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No penalty-prone blocks in this scope.</p>
            )}
          </ReportSection>
          <ReportSection title="8. Low-availability GPs">
            {report.lowAvailabilityGps.length ? (
              <ul className="space-y-1.5 text-sm">
                {report.lowAvailabilityGps.map((g) => (
                  <li key={g.id} className="flex justify-between gap-3">
                    <span className="truncate">
                      {g.name} <span className="text-xs text-muted-foreground">· {g.blockName}</span>
                    </span>
                    <span className="tabular shrink-0 font-medium text-critical-text">{formatPercent(g.availability, 2)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No GPs below the penalty threshold in this scope.</p>
            )}
          </ReportSection>
        </div>

        <ReportSection title="9. Data-quality exceptions">
          <ul className="divide-y divide-border/60 text-sm">
            {report.dataQuality.map((q) => (
              <li key={q.label} className="flex items-center justify-between gap-3 py-2">
                <span>{q.label}</span>
                <StatusBadge tone={q.count === 0 ? "good" : q.severity === "critical" ? "critical" : "warning"}>{formatCount(q.count)}</StatusBadge>
              </li>
            ))}
          </ul>
        </ReportSection>

        <footer className="border-t border-border pt-4 text-xs text-subtle-foreground">
          {report.isDemo
            ? "This preview is built from generated demo data in the browser. It is not a verified production report and must not be used for operational or contractual decisions."
            : `Computed from ${report.sourceFile ?? "the imported master data"} (data as of ${formatDate(report.dataAsOf ?? null)}). Month-to-date figures run from the 1st of the month (or the GP's AMC date) to the reporting week end. NA values are excluded, never counted as 0%.`}
        </footer>
      </div>
    </article>
  );
}

function ReportSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

function Trend({ row }: { row: ReportComparisonRow }) {
  if (row.current == null || row.previous == null) return <span className="text-muted-foreground">NA</span>;
  const d = row.current - row.previous;
  const good = row.polarity === "neutral" || d === 0 ? null : (row.polarity === "up") === d > 0;
  const Icon = d > 0 ? ArrowUpRight : d < 0 ? ArrowDownRight : ArrowRight;
  const label = d === 0 ? "No change" : good == null ? (d > 0 ? "Up" : "Down") : good ? "Better" : "Worse";
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium", good == null ? "text-muted-foreground" : good ? "text-good-text" : "text-critical-text")}>
      <Icon className="size-3.5" aria-hidden />
      {label}
    </span>
  );
}
