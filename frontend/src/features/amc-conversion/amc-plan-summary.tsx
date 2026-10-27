"use client";

import { ArrowRight, CalendarCheck2, CalendarClock, CalendarDays, CircleCheckBig } from "lucide-react";
import Link from "next/link";
import { InfoTip } from "@/components/feedback/badges";
import { ErrorState, LoadingLabel } from "@/components/feedback/states";
import { Card, Skeleton } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { api, type AmcPlanCounts, type KpiListKind } from "@/lib/api";
import { KPI_LIST_PATH, kpiListHref } from "@/lib/kpi-lists";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate } from "@/lib/utils/format";

const dayMonth = (iso: string) => formatDate(iso).slice(0, 6);
const DAY = 86_400_000;
const daysBetween = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / DAY) + 1;
/** One colour per state (same palette as the Circle Overview cards). */
const STATE_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-7)"];

/** Achieved share: green at 100%+, amber from 75%, red below. */
const pctTone = (v: number | null) => (v == null ? "text-muted-foreground" : v >= 100 ? "text-good-text" : v >= 75 ? "text-warning-text" : "text-critical-text");
const pctBg = (v: number | null) => (v == null ? "bg-muted" : v >= 100 ? "bg-good-soft" : v >= 75 ? "bg-warning-soft" : "bg-critical-soft");
const fmtPct = (v: number | null) => (v == null ? "NA" : `${v.toFixed(1)}%`);

type StateValue = { name: string; value: number; color: string; noPlan: boolean };

/**
 * Summary (KPIs): the GP-wise AMC plan of the master data file, counted – Planned Date = target, Ach Date = achieved.
 * Row 1 = targets (month, week), row 2 = what was achieved against them (month to date, week), so each column
 * reads top-down: target → achieved. Month figures = so far this month (latest data); week = the week chosen in
 * the top bar. Every card opens the GPs behind it.
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

  // State filter: that state's counts; the per-state line is not needed then.
  const t = r ? (circle ? (r.rows.find((x) => x.id === circle) ?? r.total) : r.total) : undefined;
  const rows = circle ? [] : (r?.rows ?? []);
  // With a state selected, the "no plan for <other states>" note is replaced by one about this state only.
  const warnings = !r ? [] : !circle ? r.warnings : [...r.warnings.filter((w) => !w.startsWith("No GP-wise plan in the file for")), ...(t && t.planGps === 0 && r.hasPlan ? [`No GP-wise plan in the file for ${t.name} – counted as 0.`] : [])];
  const weekDays = r ? Math.max(0, Math.min(7, daysBetween(r.week.start, r.asOf))) : 0;
  const L = !r || !t;
  const byState = (pick: (x: AmcPlanCounts) => number): StateValue[] => rows.map((x, i) => ({ name: x.name, value: pick(x), color: STATE_COLORS[i % STATE_COLORS.length], noPlan: x.planGps === 0 }));

  const monthTag = r ? `${r.month.label} · whole month` : undefined;
  const mtdTag = r ? `1 – ${dayMonth(r.monthAsOf)} · day ${r.month.daysElapsed} of ${r.month.daysInMonth}` : undefined;
  const weekTag = r ? `${r.week.label} · ${dayMonth(r.week.start)} – ${dayMonth(r.week.end)}` : undefined;
  const weekStatus = r ? (r.week.complete ? "Week complete" : `Day ${weekDays} of 7 · ${7 - weekDays} days left`) : undefined;

  return (
    <div className="space-y-6">
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

      {/* ---------------- row 1: targets ---------------- */}
      <KpiRow title="Targets" subtitle="GPs planned for AMC conversion (Planned Date in the GP sheet)">
        <PlanCard
          loading={L}
          icon={CalendarDays}
          tone="var(--series-1)"
          label="Month target"
          tag={monthTag}
          info="GPs whose Planned Date falls in this month (whole month). Moves to the next month automatically when the data does."
          value={t?.monthTarget}
          unit="GPs planned"
          detail={t && r ? <>{formatCount(t.mtdTarget)} of them due by {dayMonth(r.monthAsOf)} (month to date)</> : undefined}
          states={byState((x) => x.monthTarget)}
          href={listHref("amc-plan-month")}
          linkLabel="View planned GPs"
        />
        <PlanCard
          loading={L}
          icon={CalendarClock}
          tone="var(--series-2)"
          label="Week target"
          tag={weekTag}
          info="GPs whose Planned Date falls in the reporting week (Fri–Thu)."
          value={t?.weekTarget}
          unit="GPs planned"
          detail={weekStatus}
          states={byState((x) => x.weekTarget)}
          href={listHref("amc-plan-week")}
          linkLabel="View planned GPs"
        />
      </KpiRow>

      {/* ---------------- row 2: achieved ---------------- */}
      <KpiRow title="Achieved" subtitle="GPs converted to AMC (Ach Date in the GP sheet) against the target above">
        <PlanCard
          loading={L}
          icon={CircleCheckBig}
          tone="var(--good)"
          label="(MTD) Achievement"
          tag={mtdTag}
          info="GPs whose Ach Date falls between the 1st of the month and the latest data date, against the GPs due by that date. Letter = their “Letter Status” in the file (Submitted / Pending). Click the card to see these GPs."
          value={t?.mtdAchieved}
          unit={t ? `of ${formatCount(t.mtdTarget)} due` : undefined}
          pct={t?.mtdAchievedPct ?? null}
          pctLabel="of the month-to-date target"
          detail={
            t ? (
              <>
                {fmtPct(t.monthAchievedPct)} of the full-month target ({formatCount(t.monthTarget)}) ·{" "}
                <span className={cn(t.overdue > 0 && "font-medium text-critical-text")}>{formatCount(t.overdue)} overdue</span>
              </>
            ) : undefined
          }
          letters={t ? { submitted: t.mtdLetterSubmitted, pending: t.mtdLetterPending, notRecorded: t.mtdLetterNotRecorded, note: "BSNL confirmation awaited" } : undefined}
          states={byState((x) => x.mtdAchieved)}
          href={listHref("amc-achieved-mtd")}
          linkLabel="View achieved GPs"
        />
        <PlanCard
          loading={L}
          icon={CalendarCheck2}
          tone="var(--series-3)"
          label="Achieved this week"
          tag={weekTag}
          info="GPs whose Ach Date falls in the reporting week, up to the latest data date. Letter = their “Letter Status” in the file (Submitted / Pending). Click the card to see these GPs."
          value={t?.weekAchieved}
          unit={t ? `of ${formatCount(t.weekTarget)} planned` : undefined}
          pct={t?.weekAchievedPct ?? null}
          pctLabel="of the week target"
          detail={t ? <>{formatCount(Math.max(0, t.weekTarget - t.weekAchieved))} still open{weekStatus ? ` · ${weekStatus}` : ""}</> : undefined}
          letters={t ? { submitted: t.weekLetterSubmitted, pending: t.weekLetterPending, notRecorded: t.weekLetterNotRecorded } : undefined}
          states={byState((x) => x.weekAchieved)}
          href={listHref("amc-achieved-week")}
          linkLabel="View achieved GPs"
        />
      </KpiRow>
    </div>
  );
}

/** Section heading + 2-column card grid (month left, week right). */
function KpiRow({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h2 className="text-[13px] font-extrabold uppercase tracking-[0.08em] text-subheading">{title}</h2>
        {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">{children}</div>
    </section>
  );
}

/**
 * Compact plan card: label + period tag, the number, (achieved cards) a progress bar with the % achieved,
 * one line of context, the letter status, the per-state split in one line, and the link to the GP list.
 */
function PlanCard({
  loading,
  icon: Icon,
  tone,
  label,
  tag,
  info,
  value,
  unit,
  pct,
  pctLabel,
  detail,
  letters,
  states,
  href,
  linkLabel,
}: {
  loading: boolean;
  icon: React.ComponentType<{ className?: string }>;
  tone: string;
  label: string;
  tag?: string;
  info: string;
  value?: number;
  unit?: string;
  /** achieved cards: % of the target (drives the bar and its colour) */
  pct?: number | null;
  pctLabel?: string;
  detail?: React.ReactNode;
  letters?: { submitted: number; pending: number; notRecorded: number; note?: string };
  states: StateValue[];
  href: string;
  linkLabel: string;
}) {
  const progress = pct !== undefined;
  const done = Math.min(100, Math.max(0, pct ?? 0));
  if (loading) {
    return (
      <div className="rounded-lg border border-border bg-card p-5 shadow-xs" role="status" aria-label={`Loading ${label}`}>
        <Skeleton className="h-3.5 w-36" />
        <Skeleton className="mt-4 h-8 w-28" />
        {progress && <Skeleton className="mt-3 h-2 w-full" />}
        <LoadingLabel className="mt-3" />
      </div>
    );
  }
  return (
    <div className="group relative flex flex-col rounded-lg border border-border bg-card px-4 py-3 shadow-xs transition-[box-shadow,border-color] duration-200 hover:border-primary/30 hover:shadow-md">
      {/* header: icon + label, period on the right */}
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg" style={{ background: `color-mix(in srgb, ${tone} 12%, transparent)`, color: tone }} aria-hidden>
            <Icon className="size-3.5" />
          </span>
          <span className="text-[14px] font-bold text-subheading">{label}</span>
          <InfoTip label={label} content={info} />
        </div>
        {tag && <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">{tag}</span>}
      </div>

      {/* the number (achieved cards: with the % pill) */}
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="tabular text-[23px] font-bold leading-none tracking-tight text-heading">{formatCount(value ?? null)}</span>
        {unit && <span className="text-sm font-medium text-muted-foreground">{unit}</span>}
        {progress && (
          <span className={cn("ml-auto rounded-md px-2 py-0.5 text-sm font-semibold tabular", pctBg(pct ?? null), pctTone(pct ?? null))}>
            {fmtPct(pct ?? null)}
            {pctLabel && <span className="ml-1 text-[11px] font-normal text-muted-foreground">{pctLabel}</span>}
          </span>
        )}
      </div>

      {progress && (
        // two colours: green = achieved share, red = the part still not achieved (grey when there is no target)
        <div className="mt-2.5 flex h-2 gap-0.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${fmtPct(pct ?? null)} achieved, ${pct == null ? "NA" : `${Math.max(0, 100 - pct).toFixed(1)}%`} not achieved ${pctLabel ?? ""}`}>
          {pct != null && done > 0 && <div className="h-full bg-good transition-[width] duration-500" style={{ width: `${done}%` }} />}
          {pct != null && done < 100 && <div className="h-full flex-1 bg-critical" />}
        </div>
      )}

      {detail && <p className="mt-2 text-xs text-muted-foreground">{detail}</p>}

      {letters && (
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="text-muted-foreground">Letter:</span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-good" aria-hidden />
            <b className="tabular text-good-text">{formatCount(letters.submitted)}</b> submitted
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-warning" aria-hidden />
            <b className="tabular text-warning-text">{formatCount(letters.pending)}</b> pending
          </span>
          {letters.notRecorded > 0 && <span className="text-muted-foreground">· {formatCount(letters.notRecorded)} without status</span>}
          {letters.note && <span className="italic text-subtle-foreground">· {letters.note}</span>}
        </p>
      )}

      {/* per-state split in one line (all states only) */}
      {states.length > 0 && (
        <div className="mt-3 grid grid-cols-3 gap-2 border-t border-border pt-3">
          {states.map((x) => (
            <div key={x.name} className="min-w-0">
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <span className="size-2 shrink-0 rounded-full" style={{ background: x.color }} aria-hidden />
                <span className="truncate">{x.name}</span>
              </div>
              <div className={cn("tabular text-sm font-semibold", x.noPlan && "text-xs font-normal italic text-muted-foreground")}>{x.noPlan ? "No plan in file" : formatCount(x.value)}</div>
            </div>
          ))}
        </div>
      )}

      <Link href={href} className="mt-2 inline-flex w-fit items-center gap-1 text-[13px] font-medium text-primary hover:underline" aria-label={`${linkLabel}: ${label}`}>
        {linkLabel} <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </Link>
    </div>
  );
}
