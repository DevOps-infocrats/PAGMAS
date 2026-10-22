"use client";

import { useMemo, useState } from "react";
import { BAND_COLORS, bandStackOption } from "@/components/charts/builders";
import { EChart } from "@/components/charts/echart";
import { useChartTheme } from "@/components/charts/use-chart-theme";
import { StatusBadge } from "@/components/feedback/badges";
import { SummaryTable } from "@/components/tables/summary-table";
import type { ManagementReviewResponse, ReviewBandTable, ReviewKpiRow, ReviewSection, ReviewSummary, ReviewWeeklyCell } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatDate, formatPercent } from "@/lib/utils/format";
import { CircleSelect, Delta, fmt, InsightBar, mtdRange, Panel, PeriodTable, usePresent, type PeriodRow } from "./review-parts";

type R = ManagementReviewResponse;

const tdLabel = (r: R) => r.periods.find((p) => p.kind === "mtd")?.label ?? "Month to date";

/* ------------------------------------------------------------------ Page 1: Executive summary */

const INSIGHT_TAG = {
  observation: { label: "Fact", tone: "info" },
  action: { label: "Action", tone: "good" },
  data: { label: "Data", tone: "warning" },
} as const;

/** Shown when the API response has no data for a page (e.g. the backend still runs older code). */
function MissingPage({ page }: { page: string }) {
  return (
    <div role="alert" className="rounded-lg border border-warning/50 bg-warning-soft px-4 py-3 text-sm text-warning-text">
      <p className="font-semibold">{page}: no data in the server response.</p>
      <p>
        The backend is running an older version. Restart it (Ctrl + C, then <code>.start.ps1</code> in E:PRATAPBSNLackend) and refresh this page.
      </p>
    </div>
  );
}

const shortRange = (start: string, end: string) => `${formatDate(start).slice(0, 6)} – ${formatDate(end).slice(0, 6)}`;

/** One availability KPI: current week and previous week side by side, then a plain-language change line. */
function KpiCompareCard({ k, current, previous, circles }: { k: ReviewSummary["kpis"][number]; current: ReviewSummary["periods"]["week"]; previous: ReviewSummary["periods"]["compareWeek"]; circles: R["circles"] }) {
  const present = usePresent();
  const verdict = k.trend === "better" ? "Improved" : k.trend === "worse" ? "Declined" : k.trend === "flat" ? "No change" : "No comparison";
  const tone = k.trend === "better" ? "text-good-text bg-good-soft" : k.trend === "worse" ? "text-critical-text bg-critical-soft" : "text-muted-foreground bg-muted";
  const unit = k.unitOfCount;
  const side = (title: string, label: string, range: string, value: number | null, pctV: number | null, denom: number, strong: boolean) => (
    <div className={cn("rounded-lg border", present ? "p-2.5" : "p-3", strong ? "border-primary/40 bg-card" : "border-border bg-muted/30")}>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{title}</p>
      <p className="text-sm font-semibold">
        {label} <span className="font-normal text-muted-foreground">({range})</span>
      </p>
      <p className={cn("mt-1 text-[26px] font-semibold leading-8 tabular", strong ? "text-primary" : "text-foreground")}>{fmt(value)}</p>
      <p className="text-xs text-muted-foreground">
        {unit} · {formatPercent(pctV, 2)} of {fmt(denom)} reporting {unit}
      </p>
    </div>
  );
  return (
    <div className={cn("flex flex-col rounded-xl border border-border bg-card shadow-sm", present ? "p-3" : "p-4")}>
      <p className={cn("text-[15px] font-semibold", present ? "mb-2" : "mb-3")}>{k.label}</p>
      <div className="grid grid-cols-2 gap-3">
        {side("Current week", current.label, shortRange(current.start, current.end), k.current, k.currentPct, k.currentDenominator, true)}
        {side("Previous week", previous.label, shortRange(previous.start, previous.end), k.previous, k.previousPct, k.previousDenominator, false)}
      </div>
      <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border text-sm", present ? "mt-2 pt-2" : "mt-3 pt-3")}>
        <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-semibold", tone)}>{verdict}</span>
        <span className="text-muted-foreground">
          Change <b className="text-foreground tabular">{k.delta == null ? "NA" : `${k.delta > 0 ? "+" : k.delta < 0 ? "−" : "±"}${fmt(Math.abs(k.delta))} ${unit}`}</b>
          {k.pctChange != null && ` (${k.pctChange >= 0 ? "+" : "−"}${Math.abs(k.pctChange).toFixed(1)}%)`}
          {k.ppChange != null && ` · ${k.ppChange >= 0 ? "+" : "−"}${Math.abs(k.ppChange).toFixed(2)} pp share`}
        </span>
      </div>
      {/* state-wise split of the same KPI */}
      <div className={cn("border-t border-border", present ? "mt-2 pt-2" : "mt-3 pt-3")}>
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">State-wise</p>
        <table className="w-full text-[13px]">
          <caption className="sr-only">{`${k.label} by state`}</caption>
          <thead>
            <tr className="text-xs text-muted-foreground">
              <th scope="col" className="py-1 text-left font-medium">
                State
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                {current.label}
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                {previous.label}
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Change
              </th>
            </tr>
          </thead>
          <tbody>
            {k.breakdown.map((b) => (
              <tr key={b.code} className="border-t border-border/60">
                <th scope="row" className="py-1.5 text-left font-medium">
                  {circles.find((c) => c.code === b.code)?.name ?? b.code}
                </th>
                <td className="py-1.5 text-right font-semibold tabular">{fmt(b.current)}</td>
                <td className="py-1.5 text-right tabular text-muted-foreground">{fmt(b.previous)}</td>
                <td className={cn("py-1.5 text-right font-semibold tabular", b.trend === "better" ? "text-good-text" : b.trend === "worse" ? "text-critical-text" : "text-muted-foreground")}>
                  {b.delta == null ? "NA" : `${b.delta > 0 ? "+" : b.delta < 0 ? "−" : "±"}${fmt(Math.abs(b.delta))}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ExecutiveTab({ r }: { r: R }) {
  if (!r.summary) return <MissingPage page="Executive Summary" />;
  return <ExecutiveContent r={r} />;
}

function ExecutiveContent({ r }: { r: R }) {
  const sm = r.summary;
  const p = sm.periods;
  const ht = sm.highlightTable;
  const present = usePresent();
  return (
    <div className={present ? "space-y-3" : "space-y-6"}>
      {/* period strip: the slide header / footer already carry the week in presentation mode */}
      <div className={cn("flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm", present && "hidden")}>
        <div>
          <p className="font-semibold">
            {sm.kicker} · {sm.title} · {sm.subtitle}
          </p>
          <p className="text-muted-foreground">
            Current week <b className="text-foreground">{p.week.title}</b> vs <b className="text-foreground">{p.compareWeek.title}</b> · Month <b className="text-foreground">{p.month.range}</b> vs{" "}
            <b className="text-foreground">{p.previousMonth.range}</b>
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          Data to {formatDate(p.cutoff)} · generated{" "}
          {new Date(r.generatedAt).toLocaleString("en-IN", {
            dateStyle: "medium",
            timeStyle: "short",
          })}
        </p>
      </div>

      {(sm.warnings.length > 0 || !sm.valid) && (
        <div role="alert" className="space-y-1 rounded-lg border border-warning/50 bg-warning-soft px-4 py-3 text-sm text-warning-text">
          {!sm.valid && (
            <p className="font-semibold">
              Validation failed – figures below must not be published:{" "}
              {sm.checks
                .filter((c) => !c.ok && !c.warningOnly)
                .map((c) => c.name)
                .join(", ")}
            </p>
          )}
          {sm.warnings.map((w) => (
            <p key={w}>⚠ {w}</p>
          ))}
        </div>
      )}

      {/* two cards per row on the page (cards 1–2, then card 3); all three in one row on the slide */}
      <div className={present ? "grid grid-cols-3 gap-3" : "grid gap-4 lg:grid-cols-2"}>
        {sm.kpis.map((k) => (
          <KpiCompareCard key={k.key} k={k} current={p.week} previous={p.compareWeek} circles={r.circles} />
        ))}
      </div>

      <div className={present ? "grid grid-cols-[1.65fr_1fr] gap-3" : "grid gap-4"}>
        <Panel title={ht.title} description={ht.basis} className={cn(present && "sm:p-4")}>
          <table className="w-full table-fixed text-[13px]">
            <caption className="sr-only">{ht.title}</caption>
            <thead>
              <tr className="bg-primary text-primary-foreground">
                <th scope="col" rowSpan={2} className="w-[16%] rounded-tl-lg px-3 py-2 text-left text-xs font-semibold">
                  Circle
                </th>
                <th scope="col" rowSpan={2} className="px-2 py-2 text-center text-xs font-semibold">
                  Current AMC
                  <span className="block font-normal opacity-80">as of {formatDate(ht.cutoff).slice(0, 6)}</span>
                </th>
                <th scope="colgroup" colSpan={ht.weeks.length} className="border-l border-white/20 px-2 py-1.5 text-center text-xs font-semibold">
                  GPs achieved (per week)
                </th>
                <th scope="col" rowSpan={2} className="rounded-tr-lg border-l border-white/20 px-2 py-2 text-center text-xs font-semibold">
                  {ht.monthPlanLabel}
                </th>
              </tr>
              <tr className="bg-primary/90 text-primary-foreground">
                {ht.weeks.map((w, i) => (
                  <th key={w.id} scope="col" className={cn("px-2 py-1.5 text-center text-xs font-semibold", i === 0 && "border-l border-white/20")}>
                    {w.label}
                    <span className="block whitespace-nowrap text-[11px] font-normal opacity-80">{shortRange(w.start, w.end)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...ht.rows, ht.total].map((x) => {
                const total = x.id === "all";
                return (
                  <tr key={x.id} className={cn("border-b border-border/70", total ? "bg-primary/10 font-semibold" : "odd:bg-muted/30")}>
                    <th scope="row" className="px-3 py-2 text-left font-semibold">
                      {x.name}
                    </th>
                    <td className="px-2 py-2 text-center font-semibold tabular">{fmt(x.currentAmc)}</td>
                    {x.weeklyConversions.map((v, i) => (
                      <td key={ht.weeks[i].id} className={cn("px-2 py-2 text-center tabular", i === 0 && "border-l border-border/70", i === ht.weeks.length - 1 && "font-semibold text-primary")}>
                        {fmt(v)}
                      </td>
                    ))}
                    <td className="border-l border-border/70 px-2 py-2 text-center font-semibold tabular">{x.monthPlan == null ? "—" : fmt(x.monthPlan)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Panel>
        <Panel title="Executive insights" description="Calculated from the figures on this page" className={cn(present && "sm:p-4")}>
          <ul className={present ? "space-y-2 text-[13px]" : "space-y-2.5 text-sm"}>
            {sm.insights.map((i) => (
              <li key={i.text} className="flex gap-2">
                <StatusBadge tone={INSIGHT_TAG[i.kind].tone} className="h-fit">
                  {INSIGHT_TAG[i.kind].label}
                </StatusBadge>
                <span>{i.text}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ Page 2: Target & Achievement */

/** Rajasthan / Haryana / Assam – GPs converted to AMC (AMC + incremental, by AMC date); two cards per row. Also used by the AMC conversion page. */
export function AmcConversionCards({ cc }: { cc: R["targetsPage"]["circleCards"] }) {
  const present = usePresent();
  if (!cc) return <MissingPage page="Circle AMC conversion cards" />;
  const signed = (d: number) => `${d > 0 ? "+" : d < 0 ? "−" : "±"}${fmt(Math.abs(d))}`;
  const tone = (trend: string) => (trend === "better" ? "text-good-text" : trend === "worse" ? "text-critical-text" : "text-muted-foreground");
  return (
    <div className={present ? "grid grid-cols-3 gap-3" : "grid gap-4 lg:grid-cols-2"}>
      {cc.cards.map((c) => (
        <div key={c.id} className={cn("flex flex-col rounded-xl border border-border bg-card shadow-sm", present ? "p-3.5" : "p-5")}>
          <div>
            <div>
              <p className="text-[15px] font-semibold">{c.name} – GPs converted to AMC</p>
              <p className="text-xs text-muted-foreground">AMC + incremental GPs, counted by AMC date</p>
            </div>
            <div className="mt-2 flex flex-wrap items-baseline gap-x-2">
              <p className="tabular text-2xl font-semibold text-primary">{fmt(c.amcNow)}</p>
              <p className="text-xs text-muted-foreground">
                AMC GPs as of {formatDate(cc.asOf).slice(0, 6)} · {formatPercent(c.amcPct)} of {fmt(c.revisedScope)}
              </p>
            </div>
          </div>

          <div className={cn("grid grid-cols-2", present ? "mt-2.5 gap-2" : "mt-4 gap-3")}>
            {(
              [
                ["Weekly", cc.weekLabel, cc.compareLabel, c.week],
                ["Monthly", cc.monthLabel, cc.previousMonthLabel, c.month],
              ] as const
            ).map(([title, curL, prevL, ch]) => (
              <div key={title} className={cn("rounded-lg border border-border bg-muted/30", present ? "p-2.5" : "p-3")}>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{title} conversions</p>
                <div className="mt-1 flex items-end justify-between gap-2">
                  <div>
                    <p className="text-xs text-muted-foreground">{curL}</p>
                    <p className="tabular text-2xl font-semibold">{fmt(ch.current)}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-muted-foreground">{prevL}</p>
                    <p className="tabular text-lg font-semibold text-muted-foreground">{fmt(ch.previous)}</p>
                  </div>
                </div>
                <p className={cn("mt-1 text-xs font-semibold", tone(ch.trend))}>
                  {signed(ch.delta ?? 0)} GPs
                  {ch.pctChange != null && ` (${ch.pctChange >= 0 ? "+" : "−"}${Math.abs(ch.pctChange).toFixed(1)}%)`}
                </p>
              </div>
            ))}
          </div>

          <div className={present ? "mt-2" : "mt-3"}>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">GPs converted per week</p>
            <div className="grid grid-cols-4 gap-2">
              {c.trend.map((w, i) => (
                <div key={w.label} className={cn("rounded-md border px-2 py-1.5 text-center", i === c.trend.length - 1 ? "border-primary/40 bg-primary-soft/40" : "border-border")}>
                  <p className="text-[11px] text-muted-foreground">{w.label}</p>
                  <p className="tabular font-semibold">{fmt(w.value)}</p>
                </div>
              ))}
            </div>
          </div>

          {c.baseline && (
            <div className={cn("flex items-center justify-between gap-3 border-t border-border text-sm", present ? "mt-2 pt-2" : "mt-3 pt-3")}>
              <span className="text-muted-foreground">
                AMC GPs at end of <b className="text-foreground">{c.baseline.label}</b>
              </span>
              <span>
                <b className="tabular">{fmt(c.baseline.value)}</b>
                <span className="ml-2 text-xs font-semibold text-good-text">{signed(c.baseline.sinceChange)} since</span>
              </span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

const dash = (v: number | null | undefined) => (v == null ? "—" : fmt(v));
/** Weekly closure: the new target (from the data) is lower than the old, manually set target. */
const belowOld = (c: ReviewWeeklyCell) => c.targetChange != null && c.targetChange < 0;
const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });

export function TargetsTab({ r }: { r: R }) {
  if (!r.targetsPage || !r.summary) return <MissingPage page="Target & Achievement" />;
  return <TargetsContent r={r} />;
}

function TargetsContent({ r }: { r: R }) {
  const tp = r.targetsPage;
  const rm = tp.roadmap;
  const wk = tp.weekly;
  const th = "border-l border-white/20 px-1.5 py-2 text-center text-[11px] font-semibold leading-tight";
  const present = usePresent();
  const tight = cn(present && "sm:p-4");
  return (
    <div className={present ? "space-y-3" : "space-y-6"}>
      {tp.warnings.length > 0 && (
        <div role="status" className="space-y-1 rounded-lg border border-warning/50 bg-warning-soft px-4 py-3 text-sm text-warning-text">
          {tp.warnings.map((w) => (
            <p key={w}>⚠ {w}</p>
          ))}
        </div>
      )}

      <AmcConversionCards cc={r.targetsPage.circleCards} />

      {/* on the slide: monthly plan and weekly targets side by side */}
      <div className={present ? "grid grid-cols-[1fr_2.1fr] gap-3" : "space-y-6"}>
        <Panel title={rm.title} description={rm.subtitle} className={tight}>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className={cn("w-full text-[13px]", !present && "min-w-[520px]")}>
              <caption className="sr-only">{rm.title}</caption>
              <thead className="bg-primary text-primary-foreground">
                <tr>
                  <th scope="col" className="px-4 py-2 text-left text-xs font-semibold">
                    Circle
                  </th>
                  <th scope="col" className="px-3 py-2 text-center text-xs font-semibold">
                    {tp.monthLabel} Plan
                  </th>
                  {/* achieved so far in the current month – highlighted; rolls to the next month with the data */}
                  <th scope="col" className="bg-good px-3 py-2 text-center text-xs font-semibold text-white">
                    {rm.columns.planAchieved ?? `${tp.monthLabel} MTD Achieved`}
                  </th>
                  {rm.futureMonths.map((m) => (
                    <th key={m} scope="col" className="px-3 py-2 text-center text-xs font-semibold">
                      {m}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...rm.rows, rm.total].map((x) => {
                  const total = x.id === "all";
                  return (
                    <tr key={x.id} className={cn("border-b border-border/70 last:border-0", total && "bg-primary font-semibold text-primary-foreground")}>
                      <th scope="row" className="whitespace-nowrap px-4 py-2 text-left font-semibold">
                        {x.name}
                      </th>
                      <td className="px-3 py-2 text-center tabular">{dash(x.mtdPlan)}</td>
                      <td className={cn("px-3 py-2 text-center tabular font-semibold", total ? "bg-good text-white" : "bg-good-soft text-good-text")}>
                        {dash(x.planAchieved)}
                        {x.planAchievedPct != null && (
                          <span className={cn("ml-1 text-[11px] font-normal", total ? "text-white/85" : "text-muted-foreground")}>({x.planAchievedPct.toFixed(1)}%)</span>
                        )}
                      </td>
                      {x.futurePlans.map((v, i) => (
                        <td key={i} className="px-3 py-2 text-center tabular">
                          {dash(v)}
                          {total && x.futurePlansPartial?.[i] ? "*" : ""}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            {tp.monthLabel} Plan = conversion plan of the month; {tp.monthLabel} MTD Achieved = GPs with an Ach Date from the 1st of the month
            {tp.achievedAsOf ? ` up to ${shortDate(tp.achievedAsOf)}` : ""} (same count as AMC Conversion), % of the plan; later months = monthly plans.
            {rm.total.futurePlansPartial?.some(Boolean) ? " * Overall is the sum of the circles that have a plan for that month." : ""}
          </p>
        </Panel>

        <Panel title={wk.title} description="New target = Planned Date in the week (master data file) · old target = manual plan · achieved = Ach Date in the week" className={tight}>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full table-fixed text-[13px]">
              <caption className="sr-only">{wk.title}</caption>
              {/* old : new : achieved = 25 : 32 : 43 of each week's width, so "Achieved" and its % always fit */}
              <colgroup>
                <col style={{ width: "11%" }} />
                {wk.weeks.flatMap((w) => [0.25, 0.32, 0.43].map((f, i) => <col key={`${w.id}${i}`} style={{ width: `${(89 / Math.max(1, wk.weeks.length)) * f}%` }} />))}
              </colgroup>
              <thead className="bg-primary text-primary-foreground">
                <tr>
                  <th rowSpan={2} scope="col" className="px-3 py-2 text-left text-[11px] font-semibold">
                    Circle
                  </th>
                  {wk.weeks.map((w) => (
                    <th key={w.id} colSpan={3} scope="colgroup" className={cn(th, w.current && "bg-primary-foreground/15")}>
                      {w.label}{" "}
                      <span className="font-normal">
                        ({shortDate(w.start)} – {shortDate(w.end)})
                      </span>
                      <span className="block font-normal opacity-80">{w.current ? `current week · ${w.status}` : w.status}</span>
                    </th>
                  ))}
                </tr>
                <tr className="border-t border-white/20">
                  {wk.weeks.flatMap((w) => [
                    <th key={`${w.id}o`} scope="col" className={cn(th, "font-normal opacity-80")}>
                      Old
                    </th>,
                    <th key={`${w.id}t`} scope="col" className={cn(th, "bg-amber-400/90 text-[#3b2a00]")}>
                      New target
                    </th>,
                    <th key={`${w.id}a`} scope="col" className={cn(th, "bg-good text-white")}>
                      Achieved
                    </th>,
                  ])}
                </tr>
              </thead>
              <tbody>
                {[...wk.rows, wk.total].map((x) => {
                  const total = x.id === "all";
                  return (
                    <tr key={x.id} className={cn("border-b border-border/70 last:border-0", total && "bg-primary text-primary-foreground font-semibold")}>
                      <th scope="row" className="whitespace-nowrap px-3 py-2 text-left font-semibold">
                        {x.name}
                      </th>
                      {x.weeks.flatMap((cell, i) => [
                        <td key={`${i}o`} className={cn("px-1 py-2 text-center tabular text-[12px]", total ? "text-primary-foreground/75" : "text-muted-foreground")}>
                          {cell.oldTarget == null ? "—" : <span className="line-through decoration-1">{fmt(cell.oldTarget)}</span>}
                        </td>,
                        <td
                          key={`${i}t`}
                          className={cn(
                            "px-1 py-2 text-center tabular font-semibold",
                            // new target below the old (manual) target: highlighted red (shortfall in the tooltip)
                            belowOld(cell)
                              ? total
                                ? "bg-critical text-white"
                                : "bg-critical-soft text-critical-text"
                              : total
                                ? "bg-amber-400/90 text-[#3b2a00]"
                                : "bg-amber-50 text-[#7a4a00] dark:bg-amber-400/10 dark:text-amber-300",
                          )}
                          title={belowOld(cell) ? `New target is ${fmt(-(cell.targetChange as number))} below the old target (${fmt(cell.oldTarget)})` : undefined}
                        >
                          {dash(cell.target)}
                        </td>,
                        <td
                          key={`${i}a`}
                          className={cn("px-1 py-2 text-center tabular font-semibold", total ? "bg-good text-white" : "bg-good-soft text-good-text")}
                          title={cell.achievedPct == null ? undefined : `${cell.achievedPct}% of the new target`}
                        >
                          {dash(cell.achieved)}
                          {cell.achievedPct != null && <span className={cn("block text-[10px] font-normal", total ? "text-white/85" : "text-muted-foreground")}>{cell.achievedPct.toFixed(0)}%</span>}
                        </td>,
                      ])}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            <span className="mr-1 inline-block size-2 rounded-sm bg-amber-400 align-middle" aria-hidden /> New target = GPs whose Planned Date falls in the week (from the data, updates with every new file) ·{" "}
            <span className="line-through">Old</span> = manually set target · <span className="mr-1 inline-block size-2 rounded-sm bg-good align-middle" aria-hidden /> Achieved = GPs whose Ach
            Date falls in the week, % of the new target · <span className="mr-1 inline-block size-2 rounded-sm bg-critical align-middle" aria-hidden /> Red = new target lower than the
            old target.
          </p>
        </Panel>
      </div>
      <Panel title="How the figures are calculated" description={tp.planSource ? `Plan source: ${tp.planSource}` : undefined} className={tight}>
        <ul className={present ? "grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs" : "space-y-2 text-sm"}>
          {tp.definitions.map((d) => (
            <li key={d} className="flex gap-2">
              <span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
              {d}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

export function OperationsTab({ r }: { r: R }) {
  const parts = ["scope", "hoto", "amc", "gap"] as const;
  const head = {
    scope: "Scope",
    hoto: "HOTO",
    amc: "AMC",
    gap: "Gap (scope − AMC)",
  };
  const params = [
    { key: "blocks", label: "Total blocks", unit: "count" as const },
    { key: "gps", label: "Total GPs", unit: "count" as const },
    { key: "rkm", label: "Fibre RKM", unit: "rkm" as const },
  ];
  const codes = r.circles.map((c) => c.code);
  return (
    <Panel title="Operations snapshot" description="Scope | HOTO status | AMC status | gap – blocks under AMC = blocks with at least one AMC GP">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[900px] text-sm">
          <caption className="sr-only">Scope, HOTO, AMC and gap by circle</caption>
          <thead>
            <tr className="border-b border-border bg-muted/60 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              <th rowSpan={2} scope="col" className="px-3 py-2 text-left">
                Period
              </th>
              <th rowSpan={2} scope="col" className="px-3 py-2 text-left">
                Parameter
              </th>
              {parts.map((p) => (
                <th key={p} colSpan={codes.length} scope="colgroup" className="border-l border-border px-3 py-2 text-center">
                  {head[p]}
                </th>
              ))}
            </tr>
            <tr className="border-b border-border bg-muted/40 text-[11px] font-semibold text-muted-foreground">
              {parts.flatMap((p) =>
                codes.map((c, i) => (
                  <th key={`${p}-${c}`} scope="col" className={cn("px-3 py-1.5 text-right", i === 0 && "border-l border-border")}>
                    {c}
                  </th>
                )),
              )}
            </tr>
          </thead>
          <tbody>
            {r.operations.flatMap((op) =>
              params.map((pr, pi) => (
                <tr key={`${op.label}-${pr.key}`} className={cn("border-b border-border/70", pi === params.length - 1 && "border-border")}>
                  {pi === 0 && (
                    <th rowSpan={params.length} scope="rowgroup" className="whitespace-nowrap px-3 py-2 text-left align-top font-semibold">
                      {op.label}
                    </th>
                  )}
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{pr.label}</td>
                  {parts.flatMap((p) =>
                    op.circles.map((c, i) => (
                      <td key={`${p}-${c.code}`} className={cn("whitespace-nowrap px-3 py-2 text-right tabular", i === 0 && "border-l border-border/70", p === "gap" && "text-critical-text")}>
                        {fmt(c[pr.key as "blocks" | "gps" | "rkm"][p], pr.unit)}
                      </td>
                    )),
                  )}
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------ Critical KPIs */

function kpiRows(rows: ReviewKpiRow[]): PeriodRow[] {
  return rows.map((k) => ({
    key: k.key,
    label: (
      <span>
        {k.label}
        {k.source !== "computed" && (
          <span className="ml-1 text-xs text-subtle-foreground" title="From the circle sheet (external One-Time-Up report)">
            *
          </span>
        )}
      </span>
    ),
    values: k.values.map((v) => fmt(v, k.unit)),
    strong: k.key === "amcGps",
  }));
}

export function CriticalKpiTab({ r }: { r: R }) {
  const all = r.sections.all;
  const wk = `WK-${r.week.number}`;
  return (
    <div className="space-y-6">
      <Panel title="Monthly & weekly performance – all circles" description="* One-Time-Up figures come from the circle sheets (external report)">
        <PeriodTable periods={r.periods} rows={kpiRows(all.kpis)} firstHeader="Parameter" caption="Critical KPIs for all circles" highlightKey={r.week.id} />
      </Panel>
      <InsightBar items={all.insights.kpi} />
      <Panel title={`${wk} vs WK-${r.compareWeek.number} by circle`} description="Weekly columns of the source; colour shows whether the change is an improvement">
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[720px] text-sm">
            <caption className="sr-only">Week-on-week change by circle</caption>
            <thead>
              <tr className="border-b border-border bg-muted/60 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                <th scope="col" className="px-4 py-2.5 text-left">
                  KPI
                </th>
                {[...r.circles, { id: "all", name: "All circles", code: "ALL" }].map((c) => (
                  <th key={c.id} scope="col" className="px-4 py-2.5 text-right">
                    {c.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {all.weekChange.map((row) => (
                <tr key={row.key} className="border-b border-border/70 last:border-0">
                  <th scope="row" className="whitespace-nowrap px-4 py-2 text-left font-medium">
                    {row.label}
                  </th>
                  {[...r.circles.map((c) => r.sections[c.id]), all].map((s) => {
                    const x = s.weekChange.find((w) => w.key === row.key)!;
                    return (
                      <td key={s.id} className="whitespace-nowrap px-4 py-2 text-right tabular">
                        {fmt(x.current, x.unit)} <Delta change={x} unit={x.unit} className="ml-1" />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ Blocks & GPs (per circle) */

/** Page 3 – Critical KPI – Blocks & GPs: one circle at a time (drop-down); the PPT always contains every circle. */
export function BlocksGpsTab({ r }: { r: R }) {
  const [circleId, setCircleId] = useState(r.circles[0]?.id ?? "");
  const section = r.sections[circleId];
  const ct = section?.critical;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h3 className="text-xl font-semibold">Critical KPI – Blocks &amp; GPs {section?.name}</h3>
        <CircleSelect circles={r.circles} value={circleId} onChange={setCircleId} />
      </div>
      {!ct ? (
        <MissingPage page="Critical KPI – Blocks & GPs" />
      ) : (
        <>
          <Panel title={ct.title} description="Months = monthly AMC columns · MTD = month to date from daily data (previous month: same days) · weeks = source W-nn columns · Penalty prone = block average < 90% · * One-Time-Up from the circle sheet">
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[760px] text-[13px]">
                <caption className="sr-only">{ct.title}</caption>
                <thead className="bg-primary text-primary-foreground">
                  <tr>
                    <th scope="col" className="px-4 py-2 text-left text-xs font-semibold">
                      Parameters
                    </th>
                    <th scope="col" className="px-3 py-2 text-center text-xs font-semibold">
                      Scope / Target
                    </th>
                    {ct.columns.map((col) => (
                      <th key={col.key} scope="col" className={cn("px-3 py-2 text-center text-xs font-semibold", (col.kind === "mtd" || col.kind === "ptd") && "bg-white/10")}>
                        {col.label}
                        {(col.kind === "mtd" || col.kind === "ptd") && <span className="block text-[10px] font-normal opacity-85">{mtdRange(col.endDate)}</span>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ct.rows.map((row) => (
                    <tr key={row.key} className="border-b border-border/70 last:border-0 odd:bg-muted/30">
                      <th scope="row" className="whitespace-nowrap px-4 py-2 text-left font-medium">
                        {row.label}
                        {row.source !== "computed" && <span className="ml-1 text-xs text-subtle-foreground">*</span>}
                      </th>
                      <td className="px-3 py-2 text-center font-semibold tabular">{row.scope == null ? "" : fmt(row.scope)}</td>
                      {row.values.map((v, i) => (
                        <td key={ct.columns[i].key} className={cn("px-3 py-2 text-center tabular", ct.columns[i].kind === "mtd" && "font-semibold")}>
                          {/* circle-sheet rows have no previous-month-MTD figure: shown as "—", never estimated */}
                          {v == null && ct.columns[i].kind === "ptd" && row.source !== "computed" ? <span className="text-subtle-foreground">—</span> : fmt(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          <InsightBar
            items={ct.insight.items.map((it) => ({
              ...it,
              from: ct.insight.from,
              to: ct.insight.to,
              unit: "count" as const,
            }))}
          />
        </>
      )}
    </div>
  );
}

function DistrictPanel({ r, section }: { r: R; section: ReviewSection }) {
  const td = tdLabel(r);
  return (
    <Panel title="District view" description={`${td} · lowest availability first`}>
      <SummaryTable
        caption="District summary"
        rowKey={(d) => d.id}
        rows={section.detail?.districts ?? []}
        columns={[
          { key: "name", header: "District", render: (d) => d.name },
          {
            key: "amc",
            header: "AMC GPs",
            numeric: true,
            render: (d) => fmt(d.amcGps),
          },
          {
            key: "avg",
            header: "Avg %",
            numeric: true,
            render: (d) => formatPercent(d.availability),
          },
          {
            key: "a98",
            header: ">98%",
            numeric: true,
            render: (d) => fmt(d.gpsAbove98),
          },
          {
            key: "z",
            header: "0%",
            numeric: true,
            render: (d) => fmt(d.gpsAtZero),
          },
          {
            key: "pb",
            header: `Blocks <${r.thresholds.penalty}%`,
            numeric: true,
            render: (d) => fmt(d.penaltyBlocks),
          },
        ]}
      />
    </Panel>
  );
}

/* ------------------------------------------------------------------ Block / GP network availability */

function bandRows(t: ReviewBandTable, kind: "gp" | "block", penalty: number): PeriodRow[] {
  const rows: PeriodRow[] = [];
  if (kind === "gp")
    rows.push({
      key: "scope",
      label: "Scope (AMC GPs)",
      values: t.scope.map((v) => fmt(v)),
      strong: true,
    });
  for (const b of t.bands)
    rows.push({
      key: b.band,
      label: (
        <span className="inline-flex items-center gap-2">
          <span className="size-2.5 rounded-sm" style={{ background: BAND_COLORS[b.band] }} aria-hidden />
          {b.band}
        </span>
      ),
      values: b.values.map((v) => fmt(v)),
    });
  rows.push({
    key: "total",
    label: "Total reported",
    values: t.total.map((v) => fmt(v)),
    strong: true,
  });
  rows.push({
    key: "na",
    label: "NA (not reported)",
    values: t.na.map((v) => fmt(v)),
    muted: true,
    hint: kind === "gp" ? "Under AMC but no value in the source – never counted as 0%" : "HOTO-done block without any reported AMC GP value",
  });
  rows.push({
    key: "low",
    label: `Below ${penalty}%`,
    values: t.belowPenalty.map((v) => fmt(v)),
  });
  rows.push({
    key: "avg",
    label: "Average availability",
    values: t.average.map((v) => formatPercent(v, 2)),
  });
  return rows;
}

export function NetworkTab({ r, section, kind }: { r: R; section: ReviewSection; kind: "gp" | "block" }) {
  const theme = useChartTheme();
  const table = kind === "gp" ? section.gpUptime : section.blockUptime;
  const option = useMemo(() => {
    const bands = [...table.bands].reverse();
    return bandStackOption({
      theme,
      periods: r.periods.map((p) => p.label),
      bands: bands.map((b) => b.band),
      values: Object.fromEntries(bands.map((b) => [b.band, b.values])),
      unitLabel: kind === "gp" ? "GPs" : "blocks",
    });
  }, [theme, table, r.periods, kind]);
  const noun = kind === "gp" ? "AMC GPs" : "AMC blocks";
  return (
    <div className="space-y-6">
      <Panel
        title={`${kind === "gp" ? "GP" : "Block"} network availability & uptime – ${section.name}`}
        description={
          kind === "gp"
            ? "GP performance – AMC GPs. A GP counts in a column only when it is under AMC by the column end."
            : `Full availability distribution of ${noun} (block value = mean of its AMC GPs) — focus: blocks below ${r.thresholds.penalty}%`
        }
      >
        <PeriodTable periods={r.periods} rows={bandRows(table, kind, r.thresholds.penalty)} firstHeader={kind === "gp" ? "Bucket" : "Block uptime"} caption={`${noun} by availability band`} highlightKey={r.week.id} />
      </Panel>
      <InsightBar items={kind === "gp" ? section.insights.gp : section.insights.block} />
      <div className={cn("grid gap-4", kind === "gp" && "xl:grid-cols-[1.3fr_1fr]")}>
        <Panel title={`${noun} by availability band`} description="Stacked counts per period">
          <EChart option={option} height={340} ariaLabel={`${noun} by availability band for ${section.name}`} />
        </Panel>
        {kind === "gp" && <DistrictPanel r={r} section={section} />}
      </div>
    </div>
  );
}

/** Column order of the Page 4 / 5 tables: completed months, month TDs, then the weeks oldest → newest
 *  labelled WK-nn (e.g. … Oct-26 TD, WK-38, WK-39, WK-40, WK-41). Built from the review periods, so new
 *  weeks / months appear automatically. `order[i].i` = index of that column in the payload arrays. */
function useWeeksAscending(periods: R["periods"]) {
  return useMemo(() => {
    const idx = periods.map((p, i) => ({ p, i }));
    const head = idx.filter((x) => x.p.kind !== "week");
    const weeks = idx.filter((x) => x.p.kind === "week").sort((a, b) => a.p.endDate.localeCompare(b.p.endDate));
    const order = [...head, ...weeks];
    return { order, periods: order.map(({ p }) => (p.kind === "week" ? { ...p, label: `WK-${p.key.replace(/^W-/, "")}` } : p)) };
  }, [periods]);
}

/** Page 4 – Block Network Availability & Uptime Performance: one circle at a time (drop-down); weeks oldest → newest. */
export function BlockNetworkTab({ r }: { r: R }) {
  const [circleId, setCircleId] = useState(r.circles[0]?.id ?? "");
  const section = r.sections[circleId];
  const { order, periods } = useWeeksAscending(r.periods);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-end gap-3">
        <CircleSelect circles={r.circles} value={circleId} onChange={setCircleId} />
      </div>
      {!section ? (
        <MissingPage page="Block Network Availability & Uptime Performance" />
      ) : (
        <>
          <Panel
            title={`Block network availability & uptime – ${section.name}`}
            description={`Full availability distribution of AMC blocks (block value = mean of its AMC GPs) — focus: blocks below ${r.thresholds.penalty}%`}
          >
            <PeriodTable
              periods={periods}
              rows={bandRows(section.blockUptime, "block", r.thresholds.penalty).map((row) => ({ ...row, values: order.map(({ i }) => row.values[i]) }))}
              firstHeader="Block uptime"
              caption={`AMC blocks by availability band – ${section.name}`}
              highlightKey={r.week.id}
            />
          </Panel>
          <InsightBar items={section.insights.block} />
        </>
      )}
    </div>
  );
}

/** Page 5 – GP Network Availability & Uptime Performance: one circle at a time (drop-down); same column order as Page 4. */
export function GpNetworkTab({ r }: { r: R }) {
  const [circleId, setCircleId] = useState(r.circles[0]?.id ?? "");
  const section = r.sections[circleId];
  const { order, periods } = useWeeksAscending(r.periods);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-end gap-3">
        <CircleSelect circles={r.circles} value={circleId} onChange={setCircleId} />
      </div>
      {!section ? (
        <MissingPage page="GP Network Availability & Uptime Performance" />
      ) : (
        <>
          <Panel title={`GP network availability & uptime – ${section.name}`} description="GP performance – AMC GPs. A GP counts in a column only when it is under AMC by the column end.">
            <PeriodTable
              periods={periods}
              rows={bandRows(section.gpUptime, "gp", r.thresholds.penalty).map((row) => ({
                ...row,
                values: order.map(({ i }) => row.values[i]),
              }))}
              firstHeader="Bucket"
              caption={`AMC GPs by availability band – ${section.name}`}
              highlightKey={r.week.id}
            />
          </Panel>
          <InsightBar items={section.insights.gp} />
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ Data notes */

export function DataNotesTab({ r }: { r: R }) {
  const dn = r.dataNotes;
  const rec = dn.reconciliation;
  const tone = {
    MATCH: "good",
    EXPLAINED: "warning",
    MISMATCH: "critical",
    NO_REFERENCE: "neutral",
  } as const;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Definitions" description="How every number on this page and in the PPT is calculated">
          <ul className="space-y-2 text-sm">
            {dn.definitions.map((d) => (
              <li key={d} className="flex gap-2">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
                {d}
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title="Data-quality checks" description={`Active file: ${r.sourceFile} · data as of ${formatDate(r.dataAsOf)}`}>
          <SummaryTable
            caption="Data-quality checks"
            rowKey={(q) => q.label}
            rows={dn.dataQuality}
            columns={[
              { key: "l", header: "Check", render: (q) => q.label },
              {
                key: "c",
                header: "Count",
                numeric: true,
                render: (q) => fmt(q.count),
              },
            ]}
          />
        </Panel>
      </div>
      <Panel
        title="Reconciliation with the O&M KEY NUMBERS"
        description={`${rec.counts.MATCH ?? 0} match · ${rec.counts.EXPLAINED ?? 0} explained · ${rec.counts.MISMATCH ?? 0} unexplained · ${rec.counts.NO_REFERENCE ?? 0} without a source value${rec.sourceMtdEnd ? ` · O&M month-to-date column ends ${formatDate(rec.sourceMtdEnd)}` : ""}`}
      >
        <SummaryTable
          caption="Reconciliation rows"
          rowKey={(x) => `${x.state}-${x.metric}`}
          rows={rec.rows}
          columns={[
            { key: "s", header: "Circle", render: (x) => x.state },
            { key: "m", header: "O&M metric", render: (x) => x.metric },
            {
              key: "r",
              header: "O&M",
              numeric: true,
              render: (x) => fmt(x.reported, /rkm|fibre/i.test(x.metric) ? "rkm" : "count"),
            },
            {
              key: "c",
              header: "Review",
              numeric: true,
              render: (x) => fmt(x.computed, /rkm|fibre/i.test(x.metric) ? "rkm" : "count"),
            },
            {
              key: "st",
              header: "Status",
              render: (x) => <StatusBadge tone={tone[x.status]}>{x.status.replace("_", " ").toLowerCase()}</StatusBadge>,
            },
            {
              key: "n",
              header: "Note",
              render: (x) => <span className="block max-w-[420px] whitespace-normal text-xs text-muted-foreground">{x.note ?? "—"}</span>,
            },
          ]}
        />
      </Panel>
    </div>
  );
}
