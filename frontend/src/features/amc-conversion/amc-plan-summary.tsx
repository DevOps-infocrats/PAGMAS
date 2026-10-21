"use client";

import { CalendarCheck2, CalendarClock, CalendarDays, CircleCheckBig } from "lucide-react";
import { ErrorState } from "@/components/feedback/states";
import { StatCard, type StatBreakdown } from "@/components/kpi/stat-card";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { api, type AmcPlanCounts, type KpiListKind } from "@/lib/api";
import { KPI_LIST_PATH, kpiListHref } from "@/lib/kpi-lists";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate } from "@/lib/utils/format";

const dayMonth = (iso: string) => formatDate(iso).slice(0, 6);
const DAY = 86_400_000;
const daysBetween = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / DAY) + 1;
/** One colour per state in the breakdown bars (same palette as the Circle Overview cards). */
const STATE_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-7)"];

/** Achieved share as coloured text: green at 100%+, amber from 75%, red below. */
function Pct({ value }: { value: number | null }) {
  if (value == null) return <span className="font-semibold">NA</span>;
  return <span className={cn("font-semibold", value >= 100 ? "text-good-text" : value >= 75 ? "text-warning-text" : "text-critical-text")}>{value.toFixed(1)}%</span>;
}

/** Letter Status of the achieved GPs: submitted (green) / pending (amber), plus "not recorded" only when there are some. */
function Letters({ submitted, pending, notRecorded, note }: { submitted: number; pending: number; notRecorded: number; note?: string }) {
  const box = "block rounded-md border px-2.5 py-1.5";
  return (
    <span className="mt-3 block">
      <span className="grid grid-cols-2 gap-2">
        <span className={cn(box, "border-good/25 bg-good-soft/60")}>
          <span className="tabular block text-sm font-semibold leading-tight text-good-text">{formatCount(submitted)}</span>
          <span className="block text-[11px] leading-tight text-muted-foreground">Letter submitted</span>
        </span>
        <span className={cn(box, "border-warning/30 bg-warning-soft/60")}>
          <span className="tabular block text-sm font-semibold leading-tight text-warning-text">{formatCount(pending)}</span>
          <span className="block text-[11px] leading-tight text-muted-foreground">Letter pending</span>
        </span>
      </span>
      {notRecorded > 0 && <span className="mt-1 block text-[11px] text-muted-foreground">{formatCount(notRecorded)} without a letter status in the file</span>}
      {note && <span className="mt-2 block text-xs font-medium italic text-muted-foreground">{note}</span>}
    </span>
  );
}

/**
 * Summary (KPIs): the GP-wise AMC plan of the master data file, counted – Planned Date = target, Ach Date = achieved.
 * Month cards = so far this month (latest data); week cards = the reporting week chosen in the top bar.
 * Cards use the dashboard's StatCard (same look as Circle Overview); a click opens the GPs behind the card.
 */
export function AmcPlanSummaryView() {
  const { period, hrefTo, filters } = useFilters();
  const q = useApiQuery(period ? `amc-plan:${period.weekId}` : null, () => api.getAmcPlanSummary(period!.weekId));
  const r = q.data ?? q.staleData;
  const circle = filters.circle;
  const listHref = (kind: KpiListKind) => kpiListHref(hrefTo(KPI_LIST_PATH, { circle, district: undefined, block: undefined, gp: undefined }), kind, "amc");
  if (q.error)
    return (
      <Card>
        <ErrorState error={q.error} onRetry={q.reload} />
      </Card>
    );

  // State filter: that state's counts; the per-state breakdown is not needed then.
  const t = r ? (circle ? (r.rows.find((x) => x.id === circle) ?? r.total) : r.total) : undefined;
  const rows = circle ? [] : (r?.rows ?? []);
  // With a state selected, the "no plan for <other states>" note is replaced by one about this state only.
  const warnings = !r ? [] : !circle ? r.warnings : [...r.warnings.filter((w) => !w.startsWith("No GP-wise plan in the file for")), ...(t && t.planGps === 0 && r.hasPlan ? [`No GP-wise plan in the file for ${t.name} – counted as 0.`] : [])];
  const weekDays = r ? Math.max(0, Math.min(7, daysBetween(r.week.start, r.asOf))) : 0;
  const L = !r;

  /** Per-state breakdown of a figure (colour dot + bar segment); a state without a plan in the file says so. */
  const byState = (pick: (x: AmcPlanCounts) => number): StatBreakdown[] =>
    rows.map((x, i) => ({ label: x.name, value: pick(x), color: STATE_COLORS[i % STATE_COLORS.length], display: x.planGps === 0 ? "No plan in file" : undefined }));
  /** Progress bar: achieved (green) vs still open (grey). */
  const progress = (achieved: number, target: number): StatBreakdown[] => [
    { label: "Achieved", value: achieved, color: "var(--good)" },
    { label: "Still open", value: Math.max(0, target - achieved), color: "var(--border)" },
  ];

  return (
    <div className="space-y-5">
      {/* ---------------- period context ---------------- */}
      {r && (
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full bg-primary-soft px-2.5 py-1 font-medium text-primary">Latest data {formatDate(r.monthAsOf)}</span>
          <span className="rounded-full bg-muted px-2.5 py-1 font-medium">
            {r.month.label} · day {r.month.daysElapsed} of {r.month.daysInMonth}
          </span>
          <span className="rounded-full bg-muted px-2.5 py-1 font-medium">
            {r.week.label} · {dayMonth(r.week.start)} – {dayMonth(r.week.end)} · {r.week.complete ? "complete" : `day ${weekDays} of 7`}
          </span>
        </div>
      )}

      {warnings.length > 0 && (
        <div role="status" className="space-y-1 rounded-lg border border-warning/50 bg-warning-soft px-4 py-3 text-sm text-warning-text">
          {warnings.map((w) => (
            <p key={w}>⚠ {w}</p>
          ))}
        </div>
      )}

      {/* ---------------- month: so far this month ---------------- */}
      <KpiRow title={r ? `${r.month.label} – monthly progress` : "Monthly progress"} subtitle={r ? `1 – ${dayMonth(r.monthAsOf)} (latest data)` : undefined}>
        <StatCard
          loading={L}
          layout="split"
          icon={CalendarDays}
          tone="var(--series-1)"
          label="Month target"
          info="GPs whose Planned Date falls in this month (whole month). Moves to the next month automatically when the data does."
          value={formatCount(t?.monthTarget)}
          unit="GPs planned"
          caption={
            t && r ? (
              <>
                {formatCount(t.mtdTarget)} due by {dayMonth(r.monthAsOf)} · <Pct value={t.monthAchievedPct} /> achieved
              </>
            ) : undefined
          }
          bar={rows.length ? byState((x) => x.monthTarget) : undefined}
          breakdown={rows.length ? byState((x) => x.monthTarget) : undefined}
          href={listHref("amc-plan-month")}
          linkLabel="View planned GPs"
        />
        <StatCard
          loading={L}
          layout="split"
          icon={CircleCheckBig}
          tone="var(--good)"
          label={r ? `Achieved in ${r.month.daysElapsed} days (MTD)` : "Achieved month-to-date"}
          info="GPs whose Ach Date falls between the 1st of the month and the latest data date. Letter = their “Letter Status” in the file (Submitted / Pending). Click the card to see these GPs."
          value={formatCount(t?.mtdAchieved)}
          unit={t && r ? `of ${formatCount(t.mtdTarget)} due` : undefined}
          caption={
            t ? (
              <>
                <Pct value={t.mtdAchievedPct} /> of the month-to-date target · {formatCount(t.overdue)} overdue
                <Letters submitted={t.mtdLetterSubmitted} pending={t.mtdLetterPending} notRecorded={t.mtdLetterNotRecorded} note="Confirmation awaited from BSNL" />
              </>
            ) : undefined
          }
          bar={t ? progress(t.mtdAchieved, t.mtdTarget) : undefined}
          breakdown={rows.length ? byState((x) => x.mtdAchieved) : undefined}
          href={listHref("amc-achieved-mtd")}
          linkLabel="View achieved GPs"
        />
      </KpiRow>

      {/* ---------------- week: the reporting week ---------------- */}
      <KpiRow title={r ? `${r.week.label} – weekly progress` : "Weekly progress"} subtitle={r ? `${dayMonth(r.week.start)} – ${dayMonth(r.week.end)} (Fri–Thu)${r.week.complete ? "" : " · in progress"}` : undefined}>
        <StatCard
          loading={L}
          layout="split"
          icon={CalendarClock}
          tone="var(--series-2)"
          label="Week target"
          info="GPs whose Planned Date falls in the reporting week (Fri–Thu)."
          value={formatCount(t?.weekTarget)}
          unit="GPs planned"
          caption={r ? `Planned ${dayMonth(r.week.start)} – ${dayMonth(r.week.end)}` : undefined}
          bar={rows.length ? byState((x) => x.weekTarget) : undefined}
          breakdown={rows.length ? byState((x) => x.weekTarget) : undefined}
          href={listHref("amc-plan-week")}
          linkLabel="View planned GPs"
        />
        <StatCard
          loading={L}
          layout="split"
          icon={CalendarCheck2}
          tone="var(--series-3)"
          label="Week achieved"
          info="GPs whose Ach Date falls in the reporting week, up to the latest data date. Letter = their “Letter Status” in the file (Submitted / Pending). Click the card to see these GPs."
          value={formatCount(t?.weekAchieved)}
          unit={t ? `of ${formatCount(t.weekTarget)} planned` : undefined}
          caption={
            t && r ? (
              <>
                <Pct value={t.weekAchievedPct} /> of the week target · {formatCount(Math.max(0, t.weekTarget - t.weekAchieved))} still open
                {r.week.complete ? "" : ` · ${7 - weekDays} days left`}
                <Letters submitted={t.weekLetterSubmitted} pending={t.weekLetterPending} notRecorded={t.weekLetterNotRecorded} />
              </>
            ) : undefined
          }
          bar={t ? progress(t.weekAchieved, t.weekTarget) : undefined}
          breakdown={rows.length ? byState((x) => x.weekAchieved) : undefined}
          href={listHref("amc-achieved-week")}
          linkLabel="View achieved GPs"
        />
      </KpiRow>
    </div>
  );
}

/** Section heading + 2-column card grid, as the KPI rows of Circle Overview. */
function KpiRow({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-subtle-foreground">{title}</h2>
        {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{children}</div>
    </section>
  );
}
