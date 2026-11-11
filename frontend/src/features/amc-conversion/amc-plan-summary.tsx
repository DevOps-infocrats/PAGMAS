"use client";

import { ArrowRight, BadgeCheck, CalendarCheck2, CalendarClock, CalendarDays, CircleCheckBig, Sparkles, Target } from "lucide-react";
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
      {/* ---------------- KPI strip: month (blue) then week (orange) – short name + big number only ---------------- */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StripKpi loading={L} icon={Target} tone="var(--series-1)" band="var(--series-1)" label="Mon Target" title={`Month target – GPs whose Planned Date falls in ${r?.month.label ?? "the month"}`} href={listHref("amc-plan-month")}>
          <Num v={t?.monthTarget} cls="text-heading" />
        </StripKpi>
        <StripKpi loading={L} icon={BadgeCheck} tone="var(--good)" band="var(--series-1)" label="Mon Ach / Rdy" title="Month: GP Achieved (AMC Date) / GP Ready (Ach Date)" href={listHref("amc-converted-mtd")}>
          <Num v={t?.monthConverted} cls="text-good-text" />
          <Sep />
          <Num v={t?.monthReady} cls="text-[var(--series-2)]" />
        </StripKpi>
        <StripKpi loading={L} icon={Sparkles} tone="var(--series-4)" band="var(--series-1)" label="Mon 5% T/R/A" title="Month, 5% Incremental: Target (Planned Date) / Ready (Ach Date) / Achieved (AMC Date)" href={listHref("amc-plan-month")}>
          <Num v={t?.incMonthTarget} cls="text-heading" />
          <Sep />
          <Num v={t?.incMtdAchieved} cls="text-[var(--series-2)]" />
          <Sep />
          <Num v={t?.incMonthConverted} cls="text-good-text" />
        </StripKpi>
        <StripKpi loading={L} icon={Target} tone="var(--series-1)" band="var(--series-2)" label="Wk Target" title={`Week target – GPs whose Planned Date falls in ${r?.week.label ?? "the week"}`} href={listHref("amc-plan-week")}>
          <Num v={t?.weekTarget} cls="text-heading" />
        </StripKpi>
        <StripKpi loading={L} icon={BadgeCheck} tone="var(--good)" band="var(--series-2)" label="Wk Ach / Rdy" title="Week: GP Achieved (AMC Date) / GP Ready (Ach Date)" href={listHref("amc-converted-week")}>
          <Num v={t?.weekConverted} cls="text-good-text" />
          <Sep />
          <Num v={t?.weekReady} cls="text-[var(--series-2)]" />
        </StripKpi>
        <StripKpi loading={L} icon={Sparkles} tone="var(--series-4)" band="var(--series-2)" label="Wk 5% T/R/A" title="Week, 5% Incremental: Target (Planned Date) / Ready (Ach Date) / Achieved (AMC Date)" href={listHref("amc-plan-week")}>
          <Num v={t?.incWeekTarget} cls="text-heading" />
          <Sep />
          <Num v={t?.incWeekAchieved} cls="text-[var(--series-2)]" />
          <Sep />
          <Num v={t?.incWeekConverted} cls="text-good-text" />
        </StripKpi>
      </div>

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
          split={t && t.incMonthTarget != null ? { label: "5% Incremental Target", value: t.incMonthTarget, rest: t.monthTarget - t.incMonthTarget } : undefined}
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
          info="GPs whose Planned Date falls in the reporting week (as in the master data sheet)."
          value={t?.weekTarget}
          unit="GPs planned"
          detail={weekStatus}
          split={t && t.incWeekTarget != null ? { label: "5% Incremental Target", value: t.incWeekTarget, rest: t.weekTarget - t.incWeekTarget } : undefined}
          states={byState((x) => x.weekTarget)}
          href={listHref("amc-plan-week")}
          linkLabel="View planned GPs"
        />
      </KpiRow>

      {/* ---------------- row 2: achieved ---------------- */}
      <KpiRow title="Achieved" subtitle="GP Ready (Ach Date) and GP Achieved (AMC Date – letter accepted by BSNL) against the target above">
        <PlanCard
          loading={L}
          icon={CircleCheckBig}
          tone="var(--good)"
          label="(MTD) Achievement"
          tag={mtdTag}
          info="Month to date (1st of the month – latest data date). Target = Planned Date in the month · GP Ready = Ach Date · GP Achieved = AMC Date (letter accepted by BSNL) · Letters = “Letter submission date AMC Incremental” of the ready GPs (filled = submitted, blank = pending). The 5% Incremental line counts only the GPs of that plan category. Click the card to see the ready GPs."
          value={t?.monthReady}
          unit={t ? `GPs ready of ${formatCount(t.monthTarget)} target` : undefined}
          pct={t?.monthReadyPct ?? null}
          pctLabel="ready"
          detail={t ? <AchievedLine achieved={t.monthConverted} ready={t.monthReady} /> : undefined}
          letters={t ? { submitted: t.monthReadyLetterSubmitted, pending: t.monthReadyLetterNotSubmitted, notRecorded: 0 } : undefined}
          incremental={
            t ? { target: t.incMonthTarget ?? 0, ready: t.incMtdAchieved ?? 0, achieved: t.incMonthConverted, submitted: t.incMonthReadyLetterSubmitted, pending: t.incMonthReadyLetterNotSubmitted } : undefined
          }
          states={byState((x) => x.monthReady)}
          href={listHref("amc-achieved-mtd")}
          linkLabel="View ready GPs"
        />
        <PlanCard
          loading={L}
          icon={CalendarCheck2}
          tone="var(--series-3)"
          label="Achieved this week"
          tag={weekTag}
          info="The selected week only (the sheet's week, up to the latest data date). Target = Planned Date in the week · GP Ready = Ach Date · GP Achieved = AMC Date (letter accepted by BSNL) · Letters = “Letter submission date AMC Incremental” of the ready GPs (filled = submitted, blank = pending). The 5% Incremental line counts only the GPs of that plan category. Click the card to see the ready GPs."
          value={t?.weekReady}
          unit={t ? `GPs ready of ${formatCount(t.weekTarget)} target` : undefined}
          pct={t?.weekReadyPct ?? null}
          pctLabel="ready"
          detail={t ? <AchievedLine achieved={t.weekConverted} ready={t.weekReady} note={weekStatus} /> : undefined}
          letters={t ? { submitted: t.weekReadyLetterSubmitted, pending: t.weekReadyLetterNotSubmitted, notRecorded: 0 } : undefined}
          incremental={
            t ? { target: t.incWeekTarget ?? 0, ready: t.incWeekAchieved ?? 0, achieved: t.incWeekConverted, submitted: t.incWeekReadyLetterSubmitted, pending: t.incWeekReadyLetterNotSubmitted } : undefined
          }
          states={byState((x) => x.weekReady)}
          href={listHref("amc-achieved-week")}
          linkLabel="View ready GPs"
        />
      </KpiRow>
    </div>
  );
}

/**
 * Period context of the Summary (latest data, month day, reporting week) – shown in the page's title bar.
 * Same request as the page (shared by key), so nothing is fetched twice.
 */
export function AmcPeriodChips() {
  const { period } = useFilters();
  const q = useApiQuery(period ? `amc-plan:${period.weekId}` : null, () => api.getAmcPlanSummary(period!.weekId));
  const r = q.data ?? q.staleData;
  if (!r) return null;
  const weekDays = Math.max(0, Math.min(7, daysBetween(r.week.start, r.asOf)));
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-xs">
      <span className="rounded-full bg-primary-soft px-2.5 py-0.5 font-medium text-primary">Latest data {formatDate(r.monthAsOf)}</span>
      <span className="rounded-full border border-border bg-card/80 px-2.5 py-0.5 font-medium text-foreground">
        {r.month.label} · day {r.month.daysElapsed} of {r.month.daysInMonth}
      </span>
      <span className="rounded-full border border-border bg-card/80 px-2.5 py-0.5 font-medium text-foreground">
        {r.week.label} · {dayMonth(r.week.start)} – {dayMonth(r.week.end)} · {r.week.complete ? "complete" : `day ${weekDays} of 7`}
      </span>
    </span>
  );
}

/** Section heading + 2-column card grid (month left, week right). */
function KpiRow({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h2 className="text-[0.8125rem] font-extrabold uppercase tracking-[0.08em] text-subheading">{title}</h2>
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
  approval,
  split,
  incremental,
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
  /** "Approval Status" of the achieved GPs: IE accepted (incl. BSNL), BSNL accepted, rejected by IE */
  approval?: { ie: number; bsnl: number; rejected: number; pending: number };
  /** "5% Incremental" part of the figure (plan category), with the "Additional Plan" rest; `of` = its own target */
  split?: { label: string; value: number; of?: number; ofLabel?: string; rest: number };
  /** achieved cards: the 5% Incremental GPs – target, ready, achieved and the letters of their ready GPs */
  incremental?: { target: number; ready: number; achieved: number; submitted: number; pending: number };
  states: StateValue[];
  href: string;
  linkLabel: string;
}) {
  const progress = pct !== undefined;
  const done = Math.min(100, Math.max(0, pct ?? 0));
  if (loading) {
    return (
      <div className="relative overflow-hidden rounded-lg border border-border bg-card p-5 shadow-xs" role="status" aria-label={`Loading ${label}`}>
        <span className="absolute inset-x-0 top-0 h-[0.1875rem]" style={{ background: tone }} aria-hidden />
        <Skeleton className="h-3.5 w-36" />
        <Skeleton className="mt-4 h-8 w-28" />
        {progress && <Skeleton className="mt-3 h-2 w-full" />}
        <LoadingLabel className="mt-3" />
      </div>
    );
  }
  return (
    <div className="group relative flex flex-col overflow-hidden rounded-lg border border-border bg-card px-4 py-3 shadow-xs transition-[box-shadow,border-color] duration-200 hover:border-primary/30 hover:shadow-md">
      <span className="absolute inset-x-0 top-0 h-[0.1875rem]" style={{ background: tone }} aria-hidden />
      {/* header: icon + label, period on the right */}
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg" style={{ background: `color-mix(in srgb, ${tone} 12%, transparent)`, color: tone }} aria-hidden>
            <Icon className="size-3.5" />
          </span>
          <span className="text-[0.875rem] font-bold text-subheading">{label}</span>
          <InfoTip label={label} content={info} />
        </div>
        {tag && <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[0.6875rem] font-medium text-muted-foreground">{tag}</span>}
      </div>

      {/* the number (achieved cards: with the % pill) */}
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="tabular text-[1.4375rem] font-bold leading-none tracking-tight text-heading">{formatCount(value ?? null)}</span>
        {unit && <span className="text-sm font-medium text-muted-foreground">{unit}</span>}
        {progress && (
          <span className={cn("ml-auto rounded-md px-2 py-0.5 text-sm font-semibold tabular", pctBg(pct ?? null), pctTone(pct ?? null))}>
            {fmtPct(pct ?? null)}
            {pctLabel && <span className="ml-1 text-[0.6875rem] font-normal text-muted-foreground">{pctLabel}</span>}
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

      {split && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-muted/60 px-2.5 py-1.5 text-[0.8125rem]">
          <span className="inline-flex items-center gap-1.5 font-semibold text-foreground">
            <span className="size-2 rounded-full bg-[var(--series-4)]" aria-hidden />
            {split.label}: <b className="tabular">{formatCount(split.value)}</b>
            {split.of != null && (
              <span className="font-normal text-muted-foreground">
                of {formatCount(split.of)} {split.ofLabel}
              </span>
            )}
          </span>
          <span className="text-muted-foreground">
            Additional Plan: <b className="tabular font-semibold text-foreground">{formatCount(split.rest)}</b>
          </span>
        </div>
      )}

      {incremental && <IncrementalBox v={incremental} />}

      {detail && <div className="mt-2 text-xs text-muted-foreground">{detail}</div>}

      {letters && (
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem] font-medium text-foreground">
          <span className="font-semibold text-foreground/80">Letter:</span>
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

      {approval && (
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.8125rem] font-medium text-foreground">
          <span className="font-semibold text-foreground/80">Approval:</span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-primary" aria-hidden />
            <b className="tabular text-primary">{formatCount(approval.ie)}</b> IE accepted
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-good" aria-hidden />
            <b className="tabular text-good-text">{formatCount(approval.bsnl)}</b> BSNL accepted
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-critical" aria-hidden />
            <b className="tabular text-critical-text">{formatCount(approval.rejected)}</b> IE rejected
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full bg-warning" aria-hidden />
            <b className="tabular text-warning-text">{formatCount(approval.pending)}</b> IE pending
          </span>
        </p>
      )}

      {/* per-state split in one line (all states only) */}
      {states.length > 0 && (
        <div className="mt-3 grid grid-cols-3 gap-2 border-t border-border pt-3">
          {states.map((x) => (
            <div key={x.name} className="min-w-0">
              <div className="flex items-center gap-1.5 text-[0.6875rem] text-muted-foreground">
                <span className="size-2 shrink-0 rounded-full" style={{ background: x.color }} aria-hidden />
                <span className="truncate">{x.name}</span>
              </div>
              <div className={cn("tabular text-sm font-semibold", x.noPlan && "text-xs font-normal italic text-muted-foreground")}>{x.noPlan ? "No plan in file" : formatCount(x.value)}</div>
            </div>
          ))}
        </div>
      )}

      <Link href={href} className="mt-2 inline-flex w-fit items-center gap-1 text-[0.8125rem] font-medium text-primary hover:underline" aria-label={`${linkLabel}: ${label}`}>
        {linkLabel} <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </Link>
    </div>
  );
}

/** GP Achieved (AMC Date) out of the GP Ready GPs, as "achieved / ready" with a small bar. */
function AchievedLine({ achieved, ready, note }: { achieved: number; ready: number; note?: string }) {
  const p = ready > 0 ? Math.min(100, (achieved / ready) * 100) : 0;
  return (
    <div className="space-y-1">
      <p className="flex flex-wrap items-center gap-x-2 text-[0.8125rem] text-foreground">
        <span className="font-semibold text-foreground/80">GP Achieved (AMC Date):</span>
        <b className="tabular text-good-text">{formatCount(achieved)}</b>
        <span className="text-muted-foreground">/ {formatCount(ready)} ready</span>
        <span className="tabular text-xs font-semibold text-good-text">{ready > 0 ? `${((achieved / ready) * 100).toFixed(1)}%` : "NA"}</span>
        {note && <span className="text-xs text-muted-foreground">· {note}</span>}
      </p>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${formatCount(achieved)} of ${formatCount(ready)} ready GPs achieved`}>
        <div className="h-full rounded-full bg-good transition-[width] duration-500" style={{ width: `${p}%` }} />
      </div>
    </div>
  );
}

/** The 5% Incremental GPs of the period: target → ready → achieved, and the letters of their ready GPs. */
function IncrementalBox({ v }: { v: { target: number; ready: number; achieved: number; submitted: number; pending: number } }) {
  const items = [
    { label: "Target", value: v.target, cls: "text-foreground" },
    { label: "Ready", value: v.ready, cls: "text-[var(--series-2)]" },
    { label: "Achieved", value: v.achieved, cls: "text-good-text" },
    { label: "Letter submitted", value: v.submitted, cls: "text-primary" },
    { label: "Letter pending", value: v.pending, cls: "text-warning-text" },
  ];
  return (
    <div className="mt-2 rounded-md bg-muted/60 px-2.5 py-1.5">
      <p className="flex items-center gap-1.5 text-[0.75rem] font-semibold text-foreground">
        <span className="size-2 rounded-full bg-[var(--series-4)]" aria-hidden />
        5% Incremental
      </p>
      <div className="mt-1 grid grid-cols-5 gap-1.5">
        {items.map((x) => (
          <div key={x.label} className="min-w-0">
            <span className={cn("tabular block text-[0.9375rem] font-bold leading-tight", x.cls)}>{formatCount(x.value)}</span>
            <span className="block text-[0.65625rem] leading-tight text-muted-foreground">{x.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- KPI strip (below the title bar) */

function Num({ v, cls }: { v: number | undefined; cls: string }) {
  return <span className={cn("tabular", cls)}>{formatCount(v ?? null)}</span>;
}

function Sep() {
  return <span className="mx-px font-normal text-subtle-foreground">/</span>;
}

/** Compact strip card (like the State Comparison strip, a little smaller): coloured top band (month blue, week orange),
 *  icon, a short name and the big number(s). The full meaning is in the tooltip; the card opens the GP list. */
function StripKpi({
  loading,
  icon: Icon,
  tone,
  band,
  label,
  title,
  href,
  children,
}: {
  loading: boolean;
  icon: React.ComponentType<{ className?: string }>;
  tone: string;
  band: string;
  label: string;
  title: string;
  href: string;
  children: React.ReactNode;
}) {
  if (loading)
    return (
      <div className="relative overflow-hidden rounded-lg border border-border bg-card px-3 py-2.5 shadow-xs" role="status" aria-label={`Loading ${label}`}>
        <span className="absolute inset-x-0 top-0 h-[0.1875rem]" style={{ background: band }} aria-hidden />
        <Skeleton className="h-3 w-20" />
        <Skeleton className="mt-2 h-5 w-16" />
      </div>
    );
  return (
    <Link
      href={href}
      title={title}
      aria-label={`${title} – open the GP list`}
      className="relative flex min-w-0 items-center gap-2.5 overflow-hidden rounded-lg border border-border bg-card px-3 py-2.5 shadow-xs transition-[border-color,box-shadow] hover:border-primary/40 hover:shadow-md"
    >
      <span className="absolute inset-x-0 top-0 h-[0.1875rem]" style={{ background: band }} aria-hidden />
      <span className="hidden size-8 shrink-0 items-center justify-center rounded-lg 2xl:flex" style={{ background: `color-mix(in srgb, ${tone} 13%, transparent)`, color: tone }} aria-hidden>
        <Icon className="size-4" />
      </span>
      <span className="min-w-0">
        <span className="block whitespace-nowrap text-[0.65625rem] font-semibold uppercase tracking-[0.04em] text-muted-foreground">{label}</span>
        <span className="block whitespace-nowrap text-[1.0625rem] font-bold leading-tight tracking-tight 2xl:text-[1.1875rem]">{children}</span>
      </span>
    </Link>
  );
}
