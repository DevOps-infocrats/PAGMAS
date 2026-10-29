"use client";

import { ArrowLeft, ArrowRight } from "lucide-react";
import { useMemo, useState } from "react";
import { BAND_COLORS } from "@/components/charts/builders";
import { ChartCard } from "@/components/charts/chart-card";
import { EChart, type EChartsOption } from "@/components/charts/echart";
import { useChartTheme } from "@/components/charts/use-chart-theme";
import { Segmented } from "@/components/ui/controls";
import { Select } from "@/components/ui/overlays";
import type { CircleInsightsResponse, PeriodBands } from "@/lib/api";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate, formatPercent, formatShortDate } from "@/lib/utils/format";
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
      className="group inline-flex h-8 items-center gap-2 rounded-full border border-border bg-card pl-3 pr-1 text-[13px] font-medium text-foreground shadow-xs transition-colors hover:border-primary/40 hover:bg-primary-soft hover:text-primary"
    >
      {showGraph ? "Table" : "Graph"}
      <span className="flex size-6 items-center justify-center rounded-full bg-primary text-primary-foreground transition-transform group-hover:translate-x-0.5">
        {showGraph ? <ArrowLeft className="size-3.5" /> : <ArrowRight className="size-3.5" />}
      </span>
    </button>
  );
}

function HeadCell({ children, first, className, compact, dense }: { children: React.ReactNode; first?: boolean; className?: string; compact?: boolean; dense?: boolean }) {
  return (
    <th
      scope="col"
      className={cn(
        "whitespace-nowrap text-[11.5px] font-bold uppercase text-subheading",
        dense ? "px-2.5 py-2 tracking-wide" : compact ? "px-1.5 py-2.5 tracking-normal" : "px-2.5 py-2.5 tracking-wider",
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
  dense,
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
  /** Compact report look: shorter rows, column dividers, width capped so the numbers stay close to their labels */
  dense?: boolean;
}) {
  const cellX = compact ? "px-1.5" : "px-2.5";
  const cellY = dense ? "py-1.5" : "py-2.5";
  const divider = dense ? "border-l border-border/60" : "";
  return (
    <div className={cn("overflow-x-auto rounded-lg border border-border", dense && "max-w-6xl shadow-xs")}>
      <table className={cn("w-full", compact ? "text-[12px]" : dense ? "text-[12.5px]" : "text-[13px]")}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className={cn("border-b border-border bg-muted", dense && "border-b-2")}>
            <HeadCell first compact={compact} dense={dense}>
              {corner}
            </HeadCell>
            {periods.map((p, i) => (
              <HeadCell key={p.key} compact={compact} dense={dense} className={cn(divider, i === highlight && "text-primary")}>
                {p.label}
                {p.sub && <span className="block text-[10px] font-normal normal-case tracking-normal text-subtle-foreground">{p.sub}</span>}
              </HeadCell>
            ))}
          </tr>
        </thead>
        <tbody className="tabular">
          {rows.map((r) => (
            <tr key={r.key} className={cn("border-b border-border/70 last:border-0 hover:bg-accent/40", r.muted && "text-muted-foreground")}>
              <th scope="row" className={cn("sticky left-0 z-10 whitespace-nowrap bg-card text-left font-medium", cellY, compact ? "px-2" : "px-3")}>
                {r.label}
              </th>
              {r.cells.map((c, i) => (
                <td key={i} className={cn("whitespace-nowrap text-right", cellY, cellX, divider, i === highlight && "bg-primary-soft/40 font-medium")}>
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
                <th scope="row" className={cn("sticky left-0 z-10 whitespace-nowrap bg-muted text-left", cellY, compact ? "px-2" : "px-3")}>
                  {f.label}
                </th>
                {f.cells.map((c, i) => (
                  <td key={i} className={cn("whitespace-nowrap text-right", cellY, cellX, divider, i === highlight && "bg-primary-soft/50")}>
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

/** Columns of the Block-wise GP Count table (dots use the same colours as the AMC GPs card). */
const GP_COUNT_COLS: { label: string; color?: string }[] = [
  { label: "#" },
  { label: "Block" },
  { label: "District" },
  { label: "Total" },
  { label: "Existing" },
  { label: "New" },
  { label: "AMC", color: "var(--series-2)" },
  { label: "Incremental", color: "var(--series-4)" },
  { label: "Non-AMC", color: "var(--na)" },
];

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
      description="GPs per block (existing + new from the Master Block sheet) with their AMC status, largest first · select a block to open it"
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
        <table className="w-full text-sm">
          <caption className="sr-only">Block-wise GP count with AMC status</caption>
          <thead>
            {/* group row: what each block of numbers means */}
            <tr className="bg-muted text-[12.5px] font-semibold text-foreground">
              <th scope="colgroup" colSpan={3} className="px-3 pt-2.5 text-left" />
              <th scope="colgroup" colSpan={3} className="border-l border-border px-3 pt-2.5 text-center">
                GPs
              </th>
              <th scope="colgroup" colSpan={3} className="border-l border-border px-3 pt-2.5 text-center">
                AMC status (revised existing GPs)
              </th>
            </tr>
            <tr className="border-b border-border bg-muted">
              {GP_COUNT_COLS.map((c, i) => (
                <th
                  key={c.label}
                  scope="col"
                  className={cn(
                    "whitespace-nowrap px-3 py-2 text-[12.5px] font-semibold text-foreground",
                    i >= 3 ? "text-right" : "text-left",
                    i === 0 && "w-10",
                    (i === 3 || i === 6) && "border-l border-border",
                  )}
                >
                  {c.color && <span className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ background: c.color }} aria-hidden />}
                  {c.label}
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
                <td className="px-3 py-2.5 text-subtle-foreground">{i + 1}</td>
                <td className="px-3 py-2.5 font-medium">
                  {b.name} <span className="ml-1 text-xs font-normal text-subtle-foreground">{b.code}</span>
                </td>
                <td className="px-3 py-2.5 text-muted-foreground">{b.districtName}</td>
                <td className="border-l border-border/70 px-3 py-2.5 text-right font-semibold">{formatCount(existing(b) + fresh(b))}</td>
                <td className="px-3 py-2.5 text-right">{formatCount(existing(b))}</td>
                <td className="px-3 py-2.5 text-right">{formatCount(b.newGps ?? null)}</td>
                <td className="border-l border-border/70 px-3 py-2.5 text-right">{formatCount(b.amcOriginalGps ?? null)}</td>
                <td className="px-3 py-2.5 text-right">{formatCount(b.incrementalGps ?? null)}</td>
                <td className={cn("px-3 py-2.5 text-right", (b.nonAmcGps ?? 0) > 0 && "font-medium text-warning-text")}>{formatCount(b.nonAmcGps ?? null)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot className="tabular">
            <tr className="border-t border-border bg-muted/50 font-semibold">
              <td className="px-3 py-2.5" colSpan={3}>
                Total ({formatCount(rows.length)} of {formatCount(all.length)} blocks)
              </td>
              <td className="border-l border-border/70 px-3 py-2.5 text-right">{formatCount(sum((b) => existing(b) + fresh(b)))}</td>
              <td className="px-3 py-2.5 text-right">{formatCount(sum(existing))}</td>
              <td className="px-3 py-2.5 text-right">{formatCount(sum(fresh))}</td>
              <td className="border-l border-border/70 px-3 py-2.5 text-right">{formatCount(sum((b) => b.amcOriginalGps ?? 0))}</td>
              <td className="px-3 py-2.5 text-right">{formatCount(sum((b) => b.incrementalGps ?? 0))}</td>
              <td className="px-3 py-2.5 text-right">{formatCount(sum((b) => b.nonAmcGps ?? 0))}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="mt-2 px-1 text-xs text-subtle-foreground">
        AMC + Incremental + Non-AMC = revised existing GPs of the block (existing GPs minus those converted to NP / closed / deducted). New GPs are not yet in the GP-wise data, so they have no AMC status.
      </p>
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

/** Short axis numbers: 2K, 4K … (exact values stay in the tooltip and the table). */
const kFmt = (v: number) => (Math.abs(v) >= 1000 ? `${Number((v / 1000).toFixed(Math.abs(v) >= 10000 ? 0 : 1))}K` : formatCount(v));

const HOTO_METRICS: Record<HotoMetric, { label: string; unit: string }> = {
  gps: { label: "GPs – HOTO done and AMC vs RFP target", unit: "GPs" },
  blocks: { label: "Blocks – HOTO done vs all blocks of the state", unit: "blocks" },
  rkm: { label: "AMC fibre route vs total fibre route", unit: "RKM" },
};

/** One reading of the latest graph point, shown above the chart. */
function Reading({ color, label, value, note, dashed }: { color: string; label: string; value: string; note?: React.ReactNode; dashed?: boolean }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-card px-3 py-2">
      <p className="flex items-center gap-1.5 text-[11.5px] font-medium text-muted-foreground">
        <span className={cn("inline-block w-3.5 shrink-0", dashed ? "border-t-2 border-dashed" : "h-1 rounded-full")} style={dashed ? { borderColor: color } : { background: color }} aria-hidden />
        <span className="truncate">{label}</span>
      </p>
      <p className="tabular mt-0.5 text-[17px] font-bold leading-tight text-heading">{value}</p>
      {note && <p className="mt-0.5 text-[11.5px] text-muted-foreground">{note}</p>}
    </div>
  );
}

export function HotoAmcStatus({ data, loading, stateName }: { data: Data; loading: boolean; stateName?: string }) {
  const t = useChartTheme();
  const [graph, setGraph] = useState(false);
  const [metric, setMetric] = useState<HotoMetric>("gps");
  const pt = data?.periodTable;
  const asOf = data?.asOf;
  const totalBlocks = data?.summary?.blocks ?? null;
  const totalRkm = data?.summary?.totalRkm ?? null;
  const order = useMemo(() => periodOrder(pt?.periods ?? []), [pt]);
  const periods = useMemo(() => order.map((i) => ({ ...pt!.periods[i], label: periodLabel(pt!.periods[i]) })), [order, pt]);
  const h = useMemo(() => order.map((i) => pt!.hotoAmc[i]).filter(Boolean), [order, pt]);
  const tdIndex = periods.findIndex((p) => p.kind === "mtd");

  // ---- graph points: the same period columns as the table, in time order (no recalculation) ----
  // Months (completed, month end) then the weeks of the current month. The previous-month-TD column is a table-only
  // comparison, and the month-TD column is left out of the graph when a week already runs past it (it would repeat the
  // same position as that week); without such a week it stays in.
  const points = useMemo(() => {
    const td = periods.find((p) => p.kind === "mtd");
    const weekCoversTd = !!td && periods.some((p) => p.kind === "week" && p.endDate >= td.endDate);
    return periods
      .map((p, i) => ({ p, v: h[i] }))
      .filter(({ p, v }) => v && p.kind !== "ptd" && !(p.kind === "mtd" && weekCoversTd))
      .sort((a, b) => a.p.endDate.localeCompare(b.p.endDate));
  }, [periods, h]);

  const target = pt?.rfpTarget?.value ?? null;
  const targetDue = pt?.rfpTarget ? periods.find((p) => p.key === pt.rfpTarget.periodKey)?.label : undefined;
  const meta = HOTO_METRICS[metric];
  const last = points.at(-1);
  const pctOf = (v: number, of: number | null) => (of ? `${((v / of) * 100).toFixed(1)}%` : "NA");
  const rangeLabel = (p: (typeof periods)[number]) => {
    if (p.kind === "month") return "month end";
    if (p.kind === "mtd") return `to ${formatShortDate(asOf ?? p.endDate)}`;
    const end = new Date(`${p.endDate}T00:00:00Z`);
    const start = new Date(end.getTime() - 6 * 86400000).toISOString().slice(0, 10);
    return `${formatShortDate(start)}–${formatShortDate(p.endDate)}`;
  };

  const option = useMemo<EChartsOption>(() => {
    const cats = points.map(({ p }) => `${p.label}\n${rangeLabel(p)}`);
    const firstWeek = points.findIndex(({ p }) => p.kind === "week" || p.kind === "mtd");
    const actual = (name: string, values: number[], color: string, area: boolean) => ({
      type: "line" as const,
      name,
      data: values,
      symbol: "circle",
      symbolSize: 8,
      showSymbol: true,
      lineStyle: { width: 2.5, color },
      itemStyle: { color, borderColor: t.surface, borderWidth: 2 },
      areaStyle: area ? { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${color}33` }, { offset: 1, color: `${color}03` }] } } : undefined,
      endLabel: { show: true, formatter: (p: { value: unknown }) => kFmt(Number(p.value)), color, fontWeight: 600, fontSize: 11, fontFamily: t.font, distance: 6 },
      emphasis: { focus: "series" as const },
      z: 3,
    });
    const reference = (name: string, value: number, color: string) => ({
      type: "line" as const,
      name,
      data: points.map(() => value),
      symbol: "none",
      lineStyle: { width: 1.5, type: [6, 4] as unknown as "dashed", color },
      itemStyle: { color },
      endLabel: { show: true, formatter: () => kFmt(value), color, fontSize: 11, fontFamily: t.font, distance: 6 },
      z: 2,
    });
    const series: Record<string, unknown>[] =
      metric === "gps"
        ? [
            actual("HOTO done GPs", points.map(({ v }) => v.hotoDoneGps), t.good, false),
            actual("AMC GPs", points.map(({ v }) => v.amcGps), t.series[1], true),
            ...(target != null ? [reference("RFP target (75% of existing)", target, t.critical)] : []),
          ]
        : metric === "blocks"
          ? [
              actual("HOTO done blocks", points.map(({ v }) => v.hotoDoneBlocks), t.series[2], true),
              ...(totalBlocks != null ? [reference("All blocks of the state", totalBlocks, t.na)] : []),
            ]
          : [
              actual("AMC fibre RKM", points.map(({ v }) => v.amcRkm), t.series[0], true),
              ...(totalRkm != null ? [reference("Total fibre route", totalRkm, t.na)] : []),
            ];
    // Weeks of the current month shaded, so monthly and weekly points are not read as equal steps.
    if (firstWeek > 0) {
      series[0] = {
        ...series[0],
        markArea: {
          silent: true,
          itemStyle: { color: "rgba(127,127,127,0.07)" },
          label: { show: true, position: "insideTop", color: t.muted, fontSize: 10.5, fontFamily: t.font, distance: 4 },
          data: [[{ name: "Weekly", xAxis: cats[firstWeek] }, { xAxis: cats[cats.length - 1] }]],
        },
      };
    }
    // RFP due month marked on the time axis (GPs view only).
    if (metric === "gps" && targetDue && target != null) {
      const dueIdx = points.findIndex(({ p }) => p.label === targetDue);
      if (dueIdx >= 0)
        series[series.length - 1] = {
          ...series[series.length - 1],
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: t.critical, type: "dotted", width: 1, opacity: 0.6 },
            label: { formatter: "RFP due", color: t.critical, fontSize: 10.5, fontFamily: t.font, position: "insideEndTop" },
            data: [{ xAxis: cats[dueIdx] }],
          },
        };
    }
    const unit = meta.unit;
    return {
      animationDuration: 500,
      grid: { left: 6, right: 54, top: 40, bottom: 6, containLabel: true },
      legend: {
        top: 0,
        left: 0,
        itemWidth: 22,
        itemHeight: 10,
        itemGap: 22,
        textStyle: { color: t.text, fontSize: 12, fontWeight: 500, fontFamily: t.font },
      },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: t.surface,
        borderColor: t.border,
        borderWidth: 1,
        padding: [10, 14],
        textStyle: { color: t.text, fontSize: 12, fontFamily: t.font },
        extraCssText: "box-shadow:0 10px 30px -8px rgba(16,24,40,.18);border-radius:10px;min-width:240px;",
        axisPointer: { type: "line", lineStyle: { color: t.axis, type: "dashed" } },
        formatter: (raw: unknown) => {
          const ps = (Array.isArray(raw) ? raw : [raw]) as { dataIndex: number; marker: string; seriesName: string; value: unknown }[];
          const pnt = points[ps[0]?.dataIndex ?? -1];
          if (!pnt) return "";
          const { p, v } = pnt;
          const head =
            p.kind === "month" ? `${p.label} · position at month end (${formatDate(p.endDate)})` : p.kind === "mtd" ? `${p.label} · up to ${formatDate(asOf ?? p.endDate)}` : `${p.label} · week ${rangeLabel(p)}`;
          const row = (marker: string, name: string, val: string, note?: string) =>
            `<div style="display:flex;justify-content:space-between;gap:18px;margin-top:2px"><span>${marker}${name}</span><span style="text-align:right"><b style="font-variant-numeric:tabular-nums">${val}</b>${note ? `<br/><span style="color:${t.muted};font-size:11px">${note}</span>` : ""}</span></div>`;
          const mk = (c: string, dashed = false) =>
            dashed
              ? `<span style="display:inline-block;width:12px;border-top:2px dashed ${c};margin-right:6px;vertical-align:middle"></span>`
              : `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${c};margin-right:6px"></span>`;
          let body = "";
          if (metric === "gps") {
            body += row(mk(t.good), "HOTO done GPs", `${formatCount(v.hotoDoneGps)} GPs`);
            const gap = target != null ? target - v.amcGps : null;
            body += row(
              mk(t.series[1]),
              "AMC GPs",
              `${formatCount(v.amcGps)} GPs`,
              target != null ? `${pctOf(v.amcGps, target)} of RFP target · ${gap! > 0 ? `${formatCount(Math.round(gap!))} GPs short` : `${formatCount(Math.round(-gap!))} GPs above`}` : undefined,
            );
            if (target != null) body += row(mk(t.critical, true), "RFP target (75% of existing)", `${formatCount(Math.round(target))} GPs`, targetDue ? `due ${targetDue}` : undefined);
          } else if (metric === "blocks") {
            body += row(mk(t.series[2]), "HOTO done blocks", `${formatCount(v.hotoDoneBlocks)} blocks`, totalBlocks != null ? `${pctOf(v.hotoDoneBlocks, totalBlocks)} of all blocks` : undefined);
            if (totalBlocks != null) body += row(mk(t.na, true), "All blocks of the state", `${formatCount(totalBlocks)} blocks`);
          } else {
            body += row(mk(t.series[0]), "AMC fibre RKM", `${rkm(v.amcRkm)} RKM`, totalRkm != null ? `${pctOf(v.amcRkm, totalRkm)} of total fibre route` : undefined);
            if (totalRkm != null) body += row(mk(t.na, true), "Total fibre route", `${rkm(totalRkm)} RKM`);
          }
          return `<div style="font-weight:600;margin-bottom:6px">${head}</div>${body}<div style="margin-top:6px;color:${t.muted};font-size:11px">Unit: ${unit}</div>`;
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: true,
        data: cats,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: t.axis } },
        axisLabel: {
          interval: 0,
          rotate: 0,
          fontFamily: t.font,
          formatter: (value: string) => {
            const [a, b] = value.split("\n");
            return `{p|${a}}\n{d|${b ?? ""}}`;
          },
          rich: {
            p: { color: t.text, fontSize: 11.5, fontWeight: 600, fontFamily: t.font, lineHeight: 16 },
            d: { color: t.muted, fontSize: 10.5, fontFamily: t.font, lineHeight: 14 },
          },
        },
      },
      yAxis: {
        type: "value",
        min: 0,
        splitNumber: 4,
        name: unit,
        nameGap: 12,
        nameTextStyle: { color: t.muted, fontSize: 11, fontFamily: t.font, align: "right" },
        splitLine: { lineStyle: { color: t.grid, type: [4, 4] } },
        axisLabel: { color: t.muted, fontSize: 11, fontFamily: t.font, formatter: kFmt },
      },
      series,
    } as EChartsOption;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, metric, t, target, targetDue, totalBlocks, totalRkm, asOf]);

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

  // Latest point readings (same values as the last graph point / its table column).
  const lv = last?.v;
  const latestName = last ? `${last.p.label} (${rangeLabel(last.p)})` : "";
  const amcGap = lv && target != null ? target - lv.amcGps : null;

  return (
    <ChartCard
      title={`HOTO / AMC Status — ${stateName ?? ""}`}
      description="Month-wise and week-wise progress, calculated from each GP's HOTO and AMC dates"
      period={asOf ? `TD = up to ${formatDate(asOf)}` : undefined}
      info={`Each column shows the position at the end of that month / week: HOTO blocks = blocks with at least one GP handed over; HOTO GPs = HOTO date on or before the column end; AMC GPs = AMC date on or before it; AMC fibre = Σ TOTAL RKM of those AMC GPs (current RKM values). RFP target = 75% of existing GPs under AMC, due in the 4th month of the AMC contract.`}
      loading={loading}
      empty={!loading && periods.length === 0}
      actions={<FlipButton showGraph={graph} onToggle={() => setGraph((g) => !g)} />}
    >
      {graph ? (
        <div key="graph" className="flip-in space-y-3">
          {/* Context + metric selector */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="min-w-0 text-[13px] text-muted-foreground">
              <b className="font-semibold text-heading">{stateName}</b> · {meta.label}
              {points.length ? (
                <>
                  {" "}
                  · {points[0].p.label} → {last?.p.label}
                </>
              ) : null}
              {asOf ? ` · data up to ${formatDate(asOf)}` : ""}
            </p>
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

          {/* Latest position at a glance (exact values) */}
          {lv && (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              {metric === "gps" ? (
                <>
                  <Reading color={t.good} label={`HOTO done GPs · ${latestName}`} value={`${formatCount(lv.hotoDoneGps)} GPs`} />
                  <Reading
                    color={t.series[1]}
                    label={`AMC GPs · ${latestName}`}
                    value={`${formatCount(lv.amcGps)} GPs`}
                    note={target != null ? `${pctOf(lv.amcGps, target)} of RFP target` : undefined}
                  />
                  {target != null && (
                    <Reading
                      dashed
                      color={t.critical}
                      label="RFP target (75% of existing)"
                      value={`${formatCount(Math.round(target))} GPs`}
                      note={amcGap != null ? (amcGap > 0 ? `${formatCount(Math.round(amcGap))} AMC GPs short` : `Met · ${formatCount(Math.round(-amcGap))} above`) : undefined}
                    />
                  )}
                </>
              ) : metric === "blocks" ? (
                <>
                  <Reading color={t.series[2]} label={`HOTO done blocks · ${latestName}`} value={`${formatCount(lv.hotoDoneBlocks)} blocks`} note={totalBlocks != null ? `${pctOf(lv.hotoDoneBlocks, totalBlocks)} of all blocks` : undefined} />
                  {totalBlocks != null && <Reading dashed color={t.na} label="All blocks of the state" value={`${formatCount(totalBlocks)} blocks`} note={`${formatCount(Math.max(0, totalBlocks - lv.hotoDoneBlocks))} blocks without HOTO`} />}
                </>
              ) : (
                <>
                  <Reading color={t.series[0]} label={`AMC fibre RKM · ${latestName}`} value={`${rkm(lv.amcRkm)} RKM`} note={totalRkm != null ? `${pctOf(lv.amcRkm, totalRkm)} of total fibre route` : undefined} />
                  {totalRkm != null && <Reading dashed color={t.na} label="Total fibre route" value={`${rkm(totalRkm)} RKM`} />}
                </>
              )}
            </div>
          )}

          <EChart option={option} height={340} ariaLabel={`${meta.label} in ${stateName}`} />
          <p className="text-[11.5px] text-muted-foreground">
            Same values as the table. Shaded area = weeks of the current month; earlier points are month-end positions. Dashed line = target / reference, not an actual value.
          </p>
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
  // Graph points: the same columns and values as the table (no new calculation), oldest first.
  const trend = useMemo(() => {
    let pts: { label: string; sub: string; head: string; end: string; v: PeriodBands }[];
    if (gView === "day") {
      const daily = (kind === "gp" ? data?.gpDailyBands : data?.blockDailyBands) ?? [];
      pts = daily.map((d) => ({
        label: d.label ?? formatDate(d.date),
        sub: "",
        head: formatDate(d.date),
        end: d.date,
        v: { counts: d.counts, reported: d.reported ?? 0, na: d.counts.NA ?? 0, average: d.average ?? null },
      }));
    } else {
      const pt = data?.periodTable;
      const vs = (kind === "gp" ? pt?.gpBands : pt?.blockBands) ?? [];
      pts = (pt?.periods ?? [])
        .map((p, i) => ({ p, v: vs[i] }))
        .filter(({ p, v }) => v && p.kind !== "ptd" && (gView === "week" ? p.kind === "week" : p.kind !== "week"))
        .map(({ p, v }) => {
          const end = new Date(`${p.endDate}T00:00:00`);
          const start = new Date(end);
          start.setDate(end.getDate() - 6);
          const startIso = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, "0")}-${String(start.getDate()).padStart(2, "0")}`; // local date, no UTC shift
          const range = `${formatShortDate(startIso)}–${formatShortDate(p.endDate)}`;
          const sub = p.kind === "week" ? range : p.kind === "mtd" ? `to ${formatShortDate(p.endDate)}` : "month";
          const head = p.kind === "week" ? `${periodLabel(p)} · ${range}` : p.kind === "mtd" ? `${p.label} · month to date (up to ${formatDate(p.endDate)})` : `${p.label} · whole month`;
          return { label: periodLabel(p), sub, head, end: p.endDate, v };
        });
    }
    pts.sort((a, b) => a.end.localeCompare(b.end));
    const value = (v: PeriodBands): number | null =>
      showKey === "avg" ? v.average : showKey === "penalty" ? penaltyBands.reduce((s, b) => s + (v.counts[b] ?? 0), 0) : (v.counts[showKey] ?? 0);
    return { points: pts, labels: pts.map((x) => x.label), values: pts.map((x) => value(x.v)) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, kind, gView, showKey, penaltyBands.length]);
  const subject = kind === "gp" ? "AMC GPs" : "Blocks";
  const measureLabel = showKey === "avg" ? "Average availability" : showKey === "penalty" ? `${subject} below ${THRESHOLDS.penalty}%` : `${subject} at ${showKey}`;
  const chartTitle = `${measureLabel} — ${gView === "day" ? `day by day (${weekLabel})` : gView === "week" ? "week by week" : "month by month"}`;
  const isPct = showKey === "avg";
  const lineColor = showKey === "avg" ? t.series[0] : showKey === "penalty" ? t.critical : showKey === top ? "#0b8fb3" : BAND_COLORS[showKey] ?? t.series[0];
  // Is a rise good? Yes for >98% and average; no for low bands / penalty.
  const riseIsGood = showKey === top || showKey === "avg" || showKey === "95–98%";
  const unitWord = isPct ? "" : kind === "gp" ? "GPs" : "blocks";
  const fmtVal = (v: number | null | undefined) => (v == null ? "NA" : isPct ? formatPercent(v, 2) : `${formatCount(v)} ${unitWord}`);
  const shareOf = (v: number | null, reported: number) => (v == null || isPct || !reported ? null : (v / reported) * 100);

  const nums = trend.values.filter((v): v is number => v != null);
  const lastIdx = trend.values.reduce<number>((acc, v, i) => (v != null ? i : acc), -1);
  const prevIdx = trend.values.slice(0, Math.max(0, lastIdx)).reduce<number>((acc, v, i) => (v != null ? i : acc), -1);
  const latest = lastIdx >= 0 ? trend.values[lastIdx] : null;
  const change = latest != null && prevIdx >= 0 && trend.values[prevIdx] != null ? latest - (trend.values[prevIdx] as number) : null;
  // Percent axis zooms to the data (as before) – said under the chart so the slope is not over-read.
  const pctMin = isPct && nums.length ? Math.max(0, Math.floor((Math.min(...nums) - 5) / 5) * 5) : 0;

  const option = useMemo<EChartsOption>(() => {
    const pts = trend.points;
    const many = pts.length > 14;
    const twoLine = pts.some((p) => p.sub);
    const avg = nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null;
    const label = (v: number) => (isPct ? `${v.toFixed(2)}%` : kFmt(v));
    return {
      animationDuration: 500,
      grid: { left: 8, right: 30, top: 44, bottom: 6, containLabel: true },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: t.surface,
        borderColor: t.border,
        borderWidth: 1,
        padding: [10, 14],
        textStyle: { color: t.text, fontSize: 12, fontFamily: t.font },
        extraCssText: "box-shadow:0 10px 30px -8px rgba(16,24,40,.18);border-radius:10px;min-width:230px;",
        axisPointer: { type: "line", lineStyle: { color: t.axis, type: "dashed" } },
        formatter: (raw: unknown) => {
          const ps = (Array.isArray(raw) ? raw : [raw]) as { dataIndex: number }[];
          const i = ps[0]?.dataIndex ?? -1;
          const pnt = pts[i];
          if (!pnt) return "";
          const v = trend.values[i];
          let prev = -1;
          for (let k = i - 1; k >= 0; k--) if (trend.values[k] != null) { prev = k; break; }
          const share = shareOf(v, pnt.v.reported);
          const row = (name: string, val: string, color?: string) =>
            `<div style="display:flex;justify-content:space-between;gap:18px;margin-top:3px"><span style="color:${t.muted}">${name}</span><b style="font-variant-numeric:tabular-nums${color ? `;color:${color}` : ""}">${val}</b></div>`;
          let html = `<div style="font-weight:700;margin-bottom:4px">${pnt.head}</div>`;
          html += `<div style="display:flex;justify-content:space-between;gap:18px"><span><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${lineColor};margin-right:6px"></span>${measureLabel}</span><b style="font-variant-numeric:tabular-nums">${fmtVal(v)}</b></div>`;
          if (share != null) html += row(`Share of ${formatCount(pnt.v.reported)} with a value`, formatPercent(share, 1));
          if (v != null && prev >= 0) {
            const d = v - (trend.values[prev] as number);
            const good = d === 0 ? null : (d > 0) === riseIsGood;
            html += row(
              `vs ${pts[prev].label}`,
              `${d > 0 ? "▲ +" : d < 0 ? "▼ −" : "± "}${isPct ? `${Math.abs(d).toFixed(2)} pp` : formatCount(Math.abs(d))}`,
              good == null ? t.muted : good ? t.good : t.critical,
            );
          }
          return html;
        },
      },
      xAxis: {
        type: "category",
        data: pts.map((p) => p.label),
        boundaryGap: true,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: t.axis } },
        axisLabel: {
          color: t.muted,
          fontSize: 11.5,
          hideOverlap: true,
          margin: 10,
          formatter: (_: string, i: number) => (twoLine ? `{p|${pts[i]?.label ?? ""}}\n{s|${pts[i]?.sub ?? ""}}` : `{p|${pts[i]?.label ?? ""}}`),
          rich: { p: { fontSize: 11.5, fontWeight: 600, color: t.text, lineHeight: 16 }, s: { fontSize: 10.5, color: t.muted, lineHeight: 14 } },
        },
      },
      yAxis: {
        type: "value",
        name: isPct ? "Availability (%)" : `${subject} (count)`,
        nameLocation: "end",
        nameGap: 14,
        nameTextStyle: { color: t.muted, fontSize: 11, align: "left" },
        min: isPct ? pctMin : 0,
        max: isPct ? 100 : undefined,
        boundaryGap: isPct ? undefined : [0, "22%"],
        minInterval: isPct ? undefined : 1,
        splitLine: { lineStyle: { color: t.grid, type: [4, 4] } },
        axisLabel: { color: t.muted, fontSize: 11, formatter: (v: number) => (isPct ? `${v}%` : kFmt(v)) },
      },
      series: [
        {
          type: "line",
          name: measureLabel,
          smooth: false, // straight segments: no invented curve between two periods
          connectNulls: false,
          symbol: "circle",
          symbolSize: 8,
          lineStyle: { width: 2.5, color: lineColor },
          itemStyle: { color: lineColor, borderColor: t.surface, borderWidth: 2 },
          // Area only on a zero-based (count) axis, where the filled height means something.
          areaStyle: isPct
            ? undefined
            : { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${lineColor}33` }, { offset: 1, color: `${lineColor}05` }] } },
          label: { show: !many, position: "top", distance: 7, color: t.text, fontSize: 11.5, fontWeight: 600, formatter: (p: { value: number }) => label(p.value) },
          labelLayout: { hideOverlap: true },
          emphasis: { focus: "series", scale: 1.4 },
          data: trend.values.map((v, i) =>
            v == null
              ? "-"
              : i === lastIdx
                ? { value: v, symbolSize: 13, label: { show: true, color: lineColor, fontWeight: 700, fontSize: 12.5 } }
                : v,
          ),
          markLine:
            avg != null && nums.length > 1
              ? {
                  silent: true,
                  symbol: "none",
                  lineStyle: { color: t.muted, type: "dashed", width: 1 },
                  label: { position: "insideEndTop", color: t.muted, fontSize: 10.5, formatter: () => `Avg ${label(avg)}` },
                  data: [{ yAxis: avg }],
                }
              : undefined,
        },
      ],
    } as EChartsOption;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t, trend, measureLabel, isPct, lineColor, subject, pctMin, riseIsGood]);

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
        <div key="graph" className="flip-in rounded-lg border border-border bg-gradient-to-b from-muted/40 to-transparent p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h4 className="flex flex-wrap items-center gap-2 text-[15px] font-bold text-subheading">
                {chartTitle}
                <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-semibold", riseIsGood ? "bg-good-soft text-good-text" : "bg-critical-soft text-critical-text")}>
                  {riseIsGood ? "Higher is better" : "Lower is better"}
                </span>
              </h4>
              <p className="mt-1 text-xs text-muted-foreground">
                {latest != null ? (
                  <>
                    Latest ({trend.points[lastIdx]?.label}): <b className="text-sm text-foreground">{fmtVal(latest)}</b>
                    {!isPct && trend.points[lastIdx]?.v.reported ? (
                      <span> · {formatPercent(shareOf(latest, trend.points[lastIdx].v.reported), 1)} of {formatCount(trend.points[lastIdx].v.reported)} with a value</span>
                    ) : null}
                    {change != null && (
                      <span className={cn("ml-2 rounded px-1.5 py-0.5 font-medium", change === 0 ? "bg-muted text-muted-foreground" : (change > 0) === riseIsGood ? "bg-good-soft text-good-text" : "bg-critical-soft text-critical-text")}>
                        {change > 0 ? "▲ +" : change < 0 ? "▼ −" : "± "}
                        {isPct ? `${Math.abs(change).toFixed(2)} pp` : formatCount(Math.abs(change))} vs {trend.points[prevIdx]?.label}
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
                <span className="text-xs font-semibold text-foreground/75">View</span>
                <Select
                  ariaLabel="Graph columns"
                  className="h-8 w-36 border-0 px-2 font-semibold shadow-none hover:bg-accent"
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
                <span className="text-xs font-semibold text-foreground/75">Show</span>
                <Select ariaLabel="Graph measure" className="h-8 w-52 border-0 px-2 font-semibold shadow-none hover:bg-accent" value={gShow} onValueChange={setGShow} options={showOptions} />
              </label>
            </div>
          </div>
          <EChart option={option} height={300} ariaLabel={chartTitle} />
          <p className="mt-1 text-[11px] text-muted-foreground">
            Same values as the table ({gView === "day" ? `days of ${weekLabel}` : gView === "week" ? "weekly columns" : "monthly columns, incl. month to date"}).{" "}
            {isPct ? `Mean availability of the ${unit} with a value; the axis starts at ${pctMin}% to show the change.` : `Count of ${unit}; NA (no value) is not included.`} Dashed line = average of the
            points shown. Hover a point for details.
          </p>
        </div>
      ) : (
        <div key={`table-${view}`} className="flip-in">
          <PeriodGrid caption={title} corner={kind === "gp" ? "Availability band" : "Block availability band"} periods={cols} rows={rows} footer={footer} highlight={highlight} dense />
        </div>
      )}
    </ChartCard>
  );
}
