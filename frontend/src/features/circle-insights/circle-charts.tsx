"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import { useMemo, useState } from "react";
import { BAND_COLORS, categoryLineOption, trendLineOption } from "@/components/charts/builders";
import { ChartCard } from "@/components/charts/chart-card";
import { EChart } from "@/components/charts/echart";
import { useChartTheme } from "@/components/charts/use-chart-theme";
import { Segmented } from "@/components/ui/controls";
import { Select } from "@/components/ui/overlays";
import type { CircleInsightsResponse, PeriodBands } from "@/lib/api";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate, formatPercent } from "@/lib/utils/format";
import type { BlockSummary } from "@/types";

type Data = CircleInsightsResponse | undefined;
const rkm = (v: number | null | undefined) => (v == null ? "NA" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

/* ------------------------------------------------------------------ shared bits */

/** Round arrow button that flips a card between its table and its graph. */
export function FlipButton({ showGraph, onToggle }: { showGraph: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={showGraph}
      aria-label={showGraph ? "Show table" : "Show graph"}
      className="group inline-flex h-9 items-center gap-2 rounded-full border border-border bg-card pl-3.5 pr-1.5 text-[13px] font-medium text-foreground shadow-sm transition-colors hover:border-primary/40 hover:bg-primary-soft/60"
    >
      {showGraph ? "Table" : "Graph"}
      <span className="flex size-6 items-center justify-center rounded-full bg-primary text-primary-foreground transition-transform group-hover:translate-x-0.5">
        {showGraph ? <ArrowLeft className="size-3.5" /> : <ArrowRight className="size-3.5" />}
      </span>
    </button>
  );
}

function HeadCell({ children, first, className, compact }: { children: React.ReactNode; first?: boolean; className?: string; compact?: boolean }) {
  return (
    <th
      scope="col"
      className={cn(
        "whitespace-nowrap py-2.5 text-[11px] font-semibold uppercase text-muted-foreground",
        compact ? "px-1.5 tracking-normal" : "px-2.5 tracking-wider",
        first ? "sticky left-0 z-10 bg-muted text-left" : "text-right",
        className,
      )}
    >
      {children}
    </th>
  );
}

/** Report table: label column + one numeric column per period. Compact so it fits without scrolling. */
export function PeriodGrid({
  caption,
  corner,
  periods,
  rows,
  footer,
  highlight,
  compact,
}: {
  caption: string;
  corner: string;
  periods: { key: string; label: string; sub?: string }[];
  rows: { key: string; label: React.ReactNode; cells: React.ReactNode[]; muted?: boolean }[];
  footer?: { key: string; label: string; cells: React.ReactNode[] }[];
  /** Index of the column to emphasise (current period) */
  highlight?: number;
  /** Tighter cells (12px, less padding) so a wide table (many columns) fits the card without a scroll bar */
  compact?: boolean;
}) {
  const cellX = compact ? "px-1.5" : "px-2.5";
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className={cn("w-full", compact ? "text-[12px]" : "text-[13px]")}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border bg-muted">
            <HeadCell first compact={compact}>
              {corner}
            </HeadCell>
            {periods.map((p, i) => (
              <HeadCell key={p.key} compact={compact} className={cn(i === highlight && "text-primary")}>
                {p.label}
                {p.sub && <span className="block text-[10px] font-normal normal-case tracking-normal text-subtle-foreground">{p.sub}</span>}
              </HeadCell>
            ))}
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map((r) => (
            <tr key={r.key} className={cn("border-b border-border/70 last:border-0 hover:bg-accent/40", r.muted && "text-muted-foreground")}>
              <th scope="row" className={cn("sticky left-0 z-10 whitespace-nowrap bg-card py-2.5 text-left font-medium", compact ? "px-2" : "px-3")}>
                {r.label}
              </th>
              {r.cells.map((c, i) => (
                <td key={i} className={cn("whitespace-nowrap py-2.5 text-right", cellX, i === highlight && "bg-primary-soft/40 font-medium")}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {footer && (
          <tfoot className="tabular">
            {footer.map((f) => (
              <tr key={f.key} className="border-t border-border bg-muted/50 font-semibold">
                <th scope="row" className={cn("sticky left-0 z-10 whitespace-nowrap bg-muted py-2.5 text-left", compact ? "px-2" : "px-3")}>
                  {f.label}
                </th>
                {f.cells.map((c, i) => (
                  <td key={i} className={cn("whitespace-nowrap py-2.5 text-right", cellX, i === highlight && "bg-primary-soft/50")}>
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tfoot>
        )}
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ 1. Block-wise GP count (table) */

type TopN = "10" | "20" | "50" | "all";

export function BlockGpCount({ data, loading, onOpen }: { data: Data; loading: boolean; onOpen: (b: BlockSummary) => void }) {
  const [top, setTop] = useState<TopN>("10");
  const all = useMemo(() => {
    const total = (b: BlockSummary) => (b.existingGps ?? b.totalGps) + (b.newGps ?? 0);
    return [...(data?.blocks ?? [])].sort((a, b) => total(b) - total(a) || a.name.localeCompare(b.name));
  }, [data]);
  const rows = top === "all" ? all : all.slice(0, Number(top));
  const sum = (k: (b: BlockSummary) => number) => rows.reduce((s, b) => s + k(b), 0);
  const existing = (b: BlockSummary) => b.existingGps ?? b.totalGps;
  const fresh = (b: BlockSummary) => b.newGps ?? 0;
  return (
    <ChartCard
      title="Block-wise GP Count"
      description="GPs per block (existing + new from the Master Block sheet), largest first · select a block to open it"
      loading={loading}
      empty={!loading && all.length === 0}
      actions={
        <div className="flex items-center gap-2">
          <span className="text-[13px] text-muted-foreground">Show</span>
          <Select
            ariaLabel="Number of blocks"
            className="h-9 w-40"
            value={top}
            onValueChange={(v) => setTop(v as TopN)}
            options={[
              { value: "10", label: "Top 10 blocks" },
              { value: "20", label: "Top 20 blocks" },
              { value: "50", label: "Top 50 blocks" },
              { value: "all", label: "All blocks" },
            ]}
          />
        </div>
      }
    >
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="sr-only">Block-wise GP count</caption>
          <thead>
            <tr className="border-b border-border bg-muted">
              {["#", "Block", "District", "Total GPs", "Existing GPs", "New GPs"].map((h, i) => (
                <th key={h} scope="col" className={cn("px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground", i >= 3 ? "text-right" : "text-left", i === 0 && "w-12")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {rows.map((b, i) => (
              <tr
                key={b.id}
                tabIndex={0}
                aria-label={`Open Block Insights for ${b.name}`}
                onClick={() => onOpen(b)}
                onKeyDown={(e) => e.key === "Enter" && onOpen(b)}
                className="cursor-pointer border-b border-border/70 last:border-0 hover:bg-accent/60 focus-visible:bg-accent"
              >
                <td className="px-4 py-2.5 text-subtle-foreground">{i + 1}</td>
                <td className="px-4 py-2.5 font-medium">
                  {b.name} <span className="ml-1 text-xs font-normal text-subtle-foreground">{b.code}</span>
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">{b.districtName}</td>
                <td className="px-4 py-2.5 text-right font-semibold">{formatCount(existing(b) + fresh(b))}</td>
                <td className="px-4 py-2.5 text-right">{formatCount(existing(b))}</td>
                <td className="px-4 py-2.5 text-right">{formatCount(b.newGps ?? null)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="tabular">
            <tr className="border-t border-border bg-muted/50 font-semibold">
              <td className="px-4 py-2.5" colSpan={3}>
                Total ({formatCount(rows.length)} of {formatCount(all.length)} blocks)
              </td>
              <td className="px-4 py-2.5 text-right">{formatCount(sum((b) => existing(b) + fresh(b)))}</td>
              <td className="px-4 py-2.5 text-right">{formatCount(sum(existing))}</td>
              <td className="px-4 py-2.5 text-right">{formatCount(sum(fresh))}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ 2. HOTO / AMC status (month + week) */

type HotoMetric = "gps" | "blocks" | "rkm";

/** Table column order: months, month TD, then the weeks oldest → newest, labelled WK-nn (e.g. WK-38 … WK-41).
 *  Built from the backend periods, so new weeks appear automatically. */
function periodOrder(periods: { key: string; kind: string; endDate: string }[]): number[] {
  const idx = periods.map((_, i) => i);
  const weeks = idx.filter((i) => periods[i].kind === "week").sort((a, b) => periods[a].endDate.localeCompare(periods[b].endDate));
  return [...idx.filter((i) => periods[i].kind !== "week"), ...weeks];
}
const periodLabel = (p: { key: string; kind: string; label: string }) => (p.kind === "week" ? `WK-${p.key.replace(/^W-/, "")}` : p.label);

export function HotoAmcStatus({ data, loading, stateName }: { data: Data; loading: boolean; stateName?: string }) {
  const t = useChartTheme();
  const [graph, setGraph] = useState(false);
  const [metric, setMetric] = useState<HotoMetric>("gps");
  const pt = data?.periodTable;
  const order = useMemo(() => periodOrder(pt?.periods ?? []), [pt]);
  const periods = useMemo(() => order.map((i) => ({ ...pt!.periods[i], label: periodLabel(pt!.periods[i]) })), [order, pt]);
  const h = useMemo(() => order.map((i) => pt!.hotoAmc[i]).filter(Boolean), [order, pt]);
  const tdIndex = periods.findIndex((p) => p.kind === "mtd");

  const option = useMemo(() => {
    // The table keeps the workbook's column order; the graph runs in time order.
    // Graph: time order; the previous-month-TD column (Sep-26 TD) is a table comparison only.
    const order = periods.map((_, i) => i).filter((i) => periods[i].kind !== "ptd").sort((a, b) => periods[a].endDate.localeCompare(periods[b].endDate) || a - b);
    const cats = order.map((i) => periods[i].label);
    const hs = order.map((i) => h[i]).filter(Boolean);
    const series =
      metric === "gps"
        ? [
            { name: "HOTO done GPs", data: hs.map((x) => x.hotoDoneGps), color: t.good },
            { name: "AMC GPs", data: hs.map((x) => x.amcGps), color: t.series[1] },
            ...(pt?.rfpTarget ? [{ name: "RFP target (75% of existing)", data: order.map(() => pt.rfpTarget.value), color: t.critical }] : []),
          ]
        : metric === "blocks"
          ? [{ name: "HOTO done blocks", data: hs.map((x) => x.hotoDoneBlocks), color: t.series[2] }]
          : [{ name: "AMC fibre RKM", data: hs.map((x) => x.amcRkm), color: t.series[0] }];
    return categoryLineOption({ theme: t, categories: cats, series, unit: metric === "rkm" ? "rkm" : "count" });
  }, [periods, h, metric, t, pt]);

  const rows = [
    {
      key: "rfp",
      label: (
        <span title={pt?.rfpTarget.basis}>
          RFP target <span className="font-normal text-muted-foreground">(75%)</span>
        </span>
      ),
      muted: true,
      cells: periods.map((p) => (pt && p.key === pt.rfpTarget.periodKey ? formatCount(Math.round(pt.rfpTarget.value)) : "–")),
    },
    { key: "hb", label: "HOTO done blocks", cells: h.map((x) => formatCount(x.hotoDoneBlocks)) },
    { key: "hg", label: "HOTO done GPs", cells: h.map((x) => formatCount(x.hotoDoneGps)) },
    { key: "amc", label: "AMC GPs", cells: h.map((x) => formatCount(x.amcGps)) },
    { key: "rkm", label: "AMC fibre RKM", cells: h.map((x) => rkm(x.amcRkm)) },
  ];

  return (
    <ChartCard
      title={`HOTO / AMC Status — ${stateName ?? ""}`}
      description="Month-wise and week-wise progress, calculated from each GP's HOTO and AMC dates"
      period={data?.asOf ? `TD = up to ${formatDate(data.asOf)}` : undefined}
      info={`Each column shows the position at the end of that month / week: HOTO blocks = blocks with at least one GP handed over; HOTO GPs = HOTO date on or before the column end; AMC GPs = AMC date on or before it; AMC fibre = Σ TOTAL RKM of those AMC GPs (current RKM values). RFP target = 75% of existing GPs, due in the 4th month of the AMC contract.`}
      loading={loading}
      empty={!loading && periods.length === 0}
      actions={<FlipButton showGraph={graph} onToggle={() => setGraph((g) => !g)} />}
    >
      {graph ? (
        <div key="graph" className="flip-in">
          <div className="mb-2 flex justify-end">
            <Segmented<HotoMetric>
              ariaLabel="Graph measure"
              value={metric}
              onChange={setMetric}
              options={[
                { value: "gps", label: "GPs" },
                { value: "blocks", label: "Blocks" },
                { value: "rkm", label: "AMC fibre RKM" },
              ]}
            />
          </div>
          <EChart option={option} height={320} ariaLabel={`HOTO and AMC progress in ${stateName}`} />
        </div>
      ) : (
        <div key="table" className="flip-in">
          <PeriodGrid caption={`HOTO / AMC status – ${stateName}`} corner="HOTO / AMC status" periods={periods.map((p) => ({ key: p.key, label: p.label }))} rows={rows} highlight={tdIndex} compact />
        </div>
      )}
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ 3–5. Uptime (GP / block) */

type UptimeView = "periods" | "daily";

export function UptimeSection({ kind, data, loading, stateName }: { kind: "gp" | "block"; data: Data; loading: boolean; stateName?: string }) {
  const t = useChartTheme();
  const [view, setView] = useState<UptimeView>("periods");
  const [graph, setGraph] = useState(false);
  // Graph: one clear trend line – which columns (month / week / day) and which measure.
  const [gView, setGView] = useState<"week" | "month" | "day">("week");
  const [gShow, setGShow] = useState<string>("top");
  const bands = data?.bands ?? Object.keys(BAND_COLORS);
  const top = bands[bands.length - 1];
  const weekLabel = data?.currentWeek ? `W-${data.currentWeek.number}` : "current week";
  const unit = kind === "gp" ? "AMC GPs" : "blocks";

  // Normalise both views to: columns + bands per column.
  const { cols, values } = useMemo(() => {
    if (view === "daily") {
      const daily = (kind === "gp" ? data?.gpDailyBands : data?.blockDailyBands) ?? [];
      return {
        cols: daily.map((d) => ({ key: d.date, label: d.label ?? formatDate(d.date), kind: "day" })),
        values: daily.map((d): PeriodBands => ({ counts: d.counts, reported: d.reported ?? 0, na: d.counts.NA ?? 0, average: d.average ?? null })),
      };
    }
    const pt = data?.periodTable;
    const periods = pt?.periods ?? [];
    const bandsByPeriod = (kind === "gp" ? pt?.gpBands : pt?.blockBands) ?? [];
    const order = periodOrder(periods);
    return {
      cols: order.map((i) => ({ key: periods[i].key, label: periodLabel(periods[i]), kind: periods[i].kind as string })),
      values: order.map((i) => bandsByPeriod[i]).filter(Boolean),
    };
  }, [data, view, kind]);
  const highlight = view === "periods" ? cols.findIndex((c) => c.kind === "mtd") : cols.length - 1;

  const bandUpper = (b: string) => Number(b.replace(/[^0-9.–-]/g, "").split(/[–-]/).pop() || 0);
  const penaltyBands = bands.filter((b) => b !== top && bandUpper(b) <= THRESHOLDS.penalty);
  const showKey = gShow === "top" ? top : gShow;
  const showOptions = [
    ...[...bands].reverse().map((b) => ({ value: b === top ? "top" : b, label: b === "0%" ? "0%" : b })),
    { value: "penalty", label: `Below ${THRESHOLDS.penalty}% (penalty)` },
    { value: "avg", label: "Average availability" },
  ];
  const trend = useMemo(() => {
    let pts: { label: string; end: string; v: PeriodBands }[];
    if (gView === "day") {
      const daily = (kind === "gp" ? data?.gpDailyBands : data?.blockDailyBands) ?? [];
      pts = daily.map((d) => ({ label: d.label ?? formatDate(d.date), end: d.date, v: { counts: d.counts, reported: d.reported ?? 0, na: d.counts.NA ?? 0, average: d.average ?? null } }));
    } else {
      const pt = data?.periodTable;
      const vs = (kind === "gp" ? pt?.gpBands : pt?.blockBands) ?? [];
      pts = (pt?.periods ?? [])
        .map((p, i) => ({ p, v: vs[i] }))
        .filter(({ p, v }) => v && p.kind !== "ptd" && (gView === "week" ? p.kind === "week" : p.kind !== "week"))
        .map(({ p, v }) => ({ label: p.label, end: p.endDate, v }));
    }
    pts.sort((a, b) => a.end.localeCompare(b.end));
    const value = (v: PeriodBands): number | null =>
      showKey === "avg" ? v.average : showKey === "penalty" ? penaltyBands.reduce((s, b) => s + (v.counts[b] ?? 0), 0) : (v.counts[showKey] ?? 0);
    return { labels: pts.map((x) => x.label), values: pts.map((x) => value(x.v)) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, kind, gView, showKey, penaltyBands.length]);
  const subject = kind === "gp" ? "AMC GPs" : "Blocks";
  const measureLabel = showKey === "avg" ? "Average availability" : showKey === "penalty" ? `${subject} below ${THRESHOLDS.penalty}%` : `${subject} at ${showKey}`;
  const chartTitle = `${measureLabel} — ${gView === "day" ? `day by day (${weekLabel})` : gView === "week" ? "week by week" : "month by month"}`;
  const isPct = showKey === "avg";
  const lineColor = showKey === "avg" ? t.series[0] : showKey === "penalty" ? t.critical : showKey === top ? "#0b8fb3" : BAND_COLORS[showKey] ?? t.series[0];
  const option = useMemo(
    () => trendLineOption({ theme: t, categories: trend.labels, values: trend.values, name: measureLabel, unit: isPct ? "percent" : "count", color: lineColor }),
    [t, trend, measureLabel, isPct, lineColor],
  );
  const lastTwo = trend.values.filter((v): v is number => v != null).slice(-2);
  const change = lastTwo.length === 2 ? lastTwo[1] - lastTwo[0] : null;
  // Is a rise good? Yes for >98% and average; no for low bands / penalty.
  const riseIsGood = showKey === top || showKey === "avg" || showKey === "95–98%";

  const title = kind === "gp" ? `GP Uptime Performance (AMC GPs) — ${stateName ?? ""}` : `Block Uptime Performance — ${stateName ?? ""}`;
  const description =
    view === "daily"
      ? `How many ${unit} fall in each availability band on every day of ${weekLabel}${data?.currentWeek ? ` (${formatDate(data.currentWeek.startDate)} – ${formatDate(data.currentWeek.endDate)})` : ""}`
      : `How many ${unit} fall in each availability band, month-wise and week-wise`;
  const info =
    kind === "gp"
      ? `Months = each GP's monthly AMC availability (GP Wise Data); TD = month-to-date from daily values; weeks = the weekly W-nn columns; days = that day's value. A GP counts from its AMC date. Bands follow the workbook: 0%, then lower ≤ value < upper, and the top band is strictly above ${THRESHOLDS.healthy}% (exactly ${THRESHOLDS.healthy}% stays in 95–${THRESHOLDS.healthy}%). NA = AMC GP with no value (not visible on NMS) – never counted as 0%.`
      : `Block value = average of its AMC GPs' availability for the column. Blocks counted = blocks with HOTO done by the column end (as in the workbook); NA = such blocks without any AMC GP value. Penalty-prone below ${THRESHOLDS.penalty}%.`;

  const orderedBands = [...bands].reverse();
  const rows = [
    ...orderedBands.map((b) => ({
      key: b,
      label: (
        <span className="inline-flex items-center gap-2">
          <span className="size-2.5 shrink-0 rounded-sm" style={{ background: BAND_COLORS[b] }} aria-hidden />
          {b}
        </span>
      ),
      cells: values.map((x) => formatCount(x.counts[b] ?? 0)),
    })),
  ];
  const footer = [
    { key: "tot", label: "Total with value", cells: values.map((x) => formatCount(x.reported)) },
    { key: "na", label: kind === "gp" ? "Not reported (NA)" : "No AMC value (NA)", cells: values.map((x) => formatCount(x.na)) },
    { key: "all", label: kind === "gp" ? "Total AMC GPs" : "Total HOTO blocks", cells: values.map((x) => formatCount(x.reported + x.na)) },
    { key: "avg", label: "Average availability", cells: values.map((x) => formatPercent(x.average, 2)) },
  ];

  return (
    <ChartCard
      title={title}
      description={description}
      info={info}
      loading={loading}
      empty={!loading && cols.length === 0}
      emptyMessage="No availability data for this period."
      actions={
        <div className="flex flex-wrap items-center justify-end gap-2">
          {!graph && (
            <Segmented<UptimeView>
              ariaLabel="Columns"
              value={view}
              onChange={setView}
              options={[
                { value: "periods", label: "Month & week" },
                { value: "daily", label: `Day-wise · ${weekLabel}` },
              ]}
            />
          )}
          <FlipButton showGraph={graph} onToggle={() => setGraph((g) => !g)} />
        </div>
      }
    >
      {graph ? (
        <div key="graph" className="flip-in rounded-xl border border-border bg-gradient-to-b from-muted/40 to-transparent p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h4 className="text-[15px] font-semibold">{chartTitle}</h4>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {trend.values.length ? (
                  <>
                    Latest <b className="text-foreground">{isPct ? formatPercent(lastTwo[lastTwo.length - 1] ?? null, 2) : formatCount(lastTwo[lastTwo.length - 1] ?? null)}</b>
                    {change != null && (
                      <span className={cn("ml-2 rounded px-1.5 py-0.5 font-medium", change === 0 ? "bg-muted text-muted-foreground" : (change > 0) === riseIsGood ? "bg-good-soft text-good-text" : "bg-critical-soft text-critical-text")}>
                        {change > 0 ? "▲ +" : change < 0 ? "▼ −" : "± "}
                        {isPct ? `${Math.abs(change).toFixed(2)} pp` : formatCount(Math.abs(change))} vs previous
                      </span>
                    )}
                  </>
                ) : (
                  "No data for this selection"
                )}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1">
                <span className="text-xs text-muted-foreground">View</span>
                <Select
                  ariaLabel="Graph columns"
                  className="h-8 w-36 border-0 px-2 font-medium"
                  value={gView}
                  onValueChange={(v) => setGView(v as "week" | "month" | "day")}
                  options={[
                    { value: "week", label: "Week" },
                    { value: "month", label: "Month" },
                    { value: "day", label: `Day · ${weekLabel}` },
                  ]}
                />
              </label>
              <label className="flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1">
                <span className="text-xs text-muted-foreground">Show</span>
                <Select ariaLabel="Graph measure" className="h-8 w-52 border-0 px-2 font-medium" value={gShow} onValueChange={setGShow} options={showOptions} />
              </label>
            </div>
          </div>
          <EChart option={option} height={330} ariaLabel={chartTitle} />
        </div>
      ) : (
        <div key={`table-${view}`} className="flip-in">
          <PeriodGrid caption={title} corner={kind === "gp" ? "Availability band" : "Block availability band"} periods={cols} rows={rows} footer={footer} highlight={highlight} />
        </div>
      )}
    </ChartCard>
  );
}
