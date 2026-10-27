"use client";

import { Activity, Ban, Boxes, Clock, ShieldOff, Trophy, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo } from "react";
import { barOption, type BarSeries } from "@/components/charts/builders";
import { ChartCard } from "@/components/charts/chart-card";
import { EChart, type EChartsOption } from "@/components/charts/echart";
import { useChartTheme, type ChartTheme } from "@/components/charts/use-chart-theme";
import type { SummaryColumn } from "@/components/tables/summary-table";
import { useFilters } from "@/hooks/use-filters";
import type { KpiListKind, OverviewResponse } from "@/lib/api";
import { KPI_LIST_PATH, kpiListHref, stateDetailHref, type KpiListGroup } from "@/lib/kpi-lists";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate } from "@/lib/utils/format";

/*
 * State Performance Comparison (Circle Overview → ?view=comparison).
 * Every figure comes from the overview payload (backend views._detail → metrics.summarize), i.e. the same rules as
 * the rest of the dashboard:
 *   Non-AMC GPs          revised existing GPs not under AMC on the week end          % of revised existing GPs
 *   HOTO pending blocks  unique blocks without any HOTO-done GP                        % of blocks
 *   GPs >98%             AMC GPs with MTD availability above 98% (exactly 98 is not)   % of reporting AMC GPs
 *   Blocks >98%          block mean of its AMC GPs' MTD above 98% (not "one GP >98%")  % of reporting blocks
 *   GPs at 0%            AMC GPs with exactly 0% MTD; NA (no data) is counted apart     % of reporting AMC GPs
 *   GPs <90%             AMC GPs with MTD below 90% (0% included)                      % of reporting AMC GPs
 * Penalty: compared by the count of GPs below 90%; no ₹ amount is shown (the project has no penalty rate).
 */

type Row = NonNullable<OverviewResponse["stateDetails"]>[number];
const STATE_ORDER = ["Rajasthan", "Assam", "Haryana"];
const H = THRESHOLDS.healthy;
const P = THRESHOLDS.penalty;

const share = (a: number | null | undefined, b: number | null | undefined) => (a != null && b ? (a / b) * 100 : null);
const pctText = (v: number | null) => (v == null ? "NA" : `${v.toFixed(1)}%`);
const sum = (rows: Row[], pick: (r: Row) => number | null | undefined) => rows.reduce((s, r) => s + (pick(r) ?? 0), 0);

/** Index of the largest value (first one on a tie); null when every value is 0 / missing. */
function leader(values: (number | null | undefined)[]): number | null {
  let best: number | null = null;
  values.forEach((v, i) => {
    if (v != null && v > 0 && (best == null || v > (values[best] ?? 0))) best = i;
  });
  return best;
}

type SeriesMeta = { labels: (i: number) => string; highlight?: number | null; highlightColor?: string };

/** barOption + per-bar labels ("count · %") and one emphasised bar (the state to look at). */
function comparisonOption(
  t: ChartTheme,
  categories: string[],
  series: BarSeries[],
  unit: "count" | "percent",
  meta: SeriesMeta[],
  legendRows = 1,
  horizontal = false,
): EChartsOption {
  const option = barOption({ theme: t, unit, categories, series, labels: true, barMaxWidth: horizontal ? 20 : 34, legendRows, horizontal, maxValue: horizontal && unit === "percent" ? 100 : undefined }) as {
    series: Record<string, unknown>[];
    grid: Record<string, unknown>;
  };
  // Horizontal: keep room on the right for the "58.3% · 2,774 GPs" labels so they never run off or overlap.
  if (horizontal) option.grid = { ...option.grid, right: 120 };
  option.series.forEach((s, si) => {
    const m = meta[si];
    if (!m) return;
    const label = s.label as Record<string, unknown> | undefined;
    if (label) label.formatter = (p: { dataIndex: number; value: unknown }) => (p.value == null || p.value === "-" ? "" : m.labels(p.dataIndex));
    if (m.highlight != null) {
      const data = s.data as unknown[];
      data[m.highlight] = { value: data[m.highlight], itemStyle: { color: m.highlightColor, borderRadius: (s.stack ? 0 : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]) as never } };
    }
  });
  return option as EChartsOption;
}

/** "Highest: Rajasthan (3,668)" chip in a chart header. */
function Leader({ label, row, value, tone = "critical" }: { label: string; row: Row | null; value?: string; tone?: "critical" | "good" }) {
  if (!row) return <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">No state above 0</span>;
  const Icon = tone === "good" ? Trophy : TriangleAlert;
  return (
    <span
      className={
        tone === "good"
          ? "inline-flex items-center gap-1.5 rounded-full bg-good-soft px-2.5 py-1 text-xs font-semibold text-good-text"
          : "inline-flex items-center gap-1.5 rounded-full bg-critical-soft px-2.5 py-1 text-xs font-semibold text-critical-text"
      }
    >
      <Icon className="size-3.5" aria-hidden />
      {label}: {row.name}
      {value ? ` (${value})` : ""}
    </span>
  );
}

/** Compact table of this page: fits a half-width card without horizontal scrolling (headers may wrap). */
function CompactTable<T>({
  columns,
  rows,
  total,
  rowKey,
  onRowClick,
  rowLabel,
  caption,
}: {
  columns: SummaryColumn<T>[];
  rows: T[];
  total?: Record<string, React.ReactNode>;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  rowLabel?: (row: T) => string;
  caption?: string;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full table-auto text-[12.5px]">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-border bg-table-head">
            {columns.map((c) => (
              <th key={c.key} scope="col" className={cn("px-2.5 py-1.5 text-[11.5px] font-semibold leading-tight text-heading", c.numeric ? "text-right" : "text-left")}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={rowKey(r)}
              tabIndex={onRowClick ? 0 : undefined}
              aria-label={onRowClick && rowLabel ? rowLabel(r) : undefined}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              onKeyDown={onRowClick ? (e) => e.key === "Enter" && e.target === e.currentTarget && onRowClick(r) : undefined}
              className={cn("border-b border-border/70 last:border-0 even:bg-muted/45", onRowClick && "cursor-pointer hover:bg-primary-soft/50 focus-visible:bg-accent")}
            >
              {columns.map((c, i) => (
                <td key={c.key} className={cn("px-2.5 py-1.5", c.numeric && "tabular whitespace-nowrap text-right", i === 0 && "font-medium")}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {total && (
          <tfoot>
            <tr className="border-t border-border bg-muted/60 font-semibold">
              {columns.map((c) => (
                <td key={c.key} className={cn("px-2.5 py-1.5", c.numeric && "tabular whitespace-nowrap text-right")}>
                  {total[c.key] ?? ""}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

/** Small KPI tile of this page: less height and width than the overview StatCard. */
function MiniKpi({
  icon: Icon,
  color,
  label,
  info,
  value,
  caption,
  loading,
}: {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  label: string;
  info: string;
  value: string;
  caption?: string;
  loading?: boolean;
}) {
  return (
    <div title={info} className="relative flex min-w-0 items-center gap-2 overflow-hidden rounded-lg border border-border bg-card px-2.5 py-1.5 shadow-xs">
      <span className="absolute inset-x-0 top-0 h-[2px]" style={{ background: color }} aria-hidden />
      <span
        className="flex size-6 shrink-0 items-center justify-center rounded-md"
        style={{ background: `color-mix(in srgb, ${color} 14%, transparent)`, color }}
        aria-hidden
      >
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0">
        <p className="truncate text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className="tabular text-[16px] font-bold leading-tight text-heading">{loading ? "…" : value}</p>
        {caption && !loading && <p className="truncate text-[10.5px] text-muted-foreground">{caption}</p>}
      </div>
    </div>
  );
}

export function StateComparison({ data, loading }: { data: OverviewResponse | undefined; loading: boolean }) {
  const t = useChartTheme();
  const router = useRouter();
  const { hrefTo } = useFilters();
  const s = data?.summary;
  const rows = useMemo(() => {
    const all = data?.stateDetails ?? [];
    const known = STATE_ORDER.map((n) => all.find((r) => r.name.toLowerCase() === n.toLowerCase())).filter((r): r is Row => !!r);
    return [...known, ...all.filter((r) => !known.includes(r))];
  }, [data]);
  const names = rows.map((r) => r.name);
  const period = data?.asOf ? `MTD up to ${formatDate(data.asOf)}` : undefined;
  const empty = !loading && rows.length === 0;

  // Drill-down: a bar or table row opens the records behind it for that state (same week).
  const base = (circleId: string) => hrefTo(KPI_LIST_PATH, { circle: circleId, district: undefined, block: undefined, gp: undefined });
  const openGroup = (circleId: string, group: KpiListGroup, kind: KpiListKind) => router.push(stateDetailHref(base(circleId), group, kind));
  const openList = (circleId: string, kind: KpiListKind) => router.push(kpiListHref(base(circleId), kind));
  const onBar = (open: (id: string) => void) => (p: { dataIndex: number }) => rows[p.dataIndex] && open(rows[p.dataIndex].id);

  /* ---------- 2. Non-AMC GPs ---------- */
  const nonAmcPct = rows.map((r) => share(r.nonAmcGps, r.revisedExisting));
  const nonAmcTop = leader(rows.map((r) => r.nonAmcGps));
  const nonAmcOption = useMemo(
    () =>
      comparisonOption(t, names, [{ name: "Non-AMC GPs", data: rows.map((r) => r.nonAmcGps), color: t.na }], "count", [
        { labels: (i) => `${formatCount(rows[i].nonAmcGps)} · ${pctText(nonAmcPct[i])}`, highlight: nonAmcTop, highlightColor: t.serious },
      ]),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, t],
  );

  /* ---------- 3. HOTO pending blocks ---------- */
  const hotoTop = leader(rows.map((r) => r.hotoPendingBlocks));
  const hotoPendingTotal = sum(rows, (r) => r.hotoPendingBlocks);
  // Donut: each state's share of the HOTO pending blocks (slices in table order, so dataIndex = row index).
  const hotoOption = useMemo<EChartsOption>(() => {
    const colors = [t.series[0], t.series[1], t.series[2], t.series[4]];
    return {
      animationDuration: 500,
      tooltip: {
        trigger: "item",
        textStyle: { fontFamily: t.font, fontSize: 12 },
        formatter: (p: { name: string; value: number; percent: number }) => `${p.name}<br/><b>${formatCount(p.value)}</b> pending blocks (${p.percent.toFixed(1)}%)`,
      },
      series: [
        {
          type: "pie",
          radius: ["50%", "72%"],
          center: ["50%", "50%"],
          avoidLabelOverlap: true,
          itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 },
          label: {
            show: true,
            color: t.text,
            fontFamily: t.font,
            fontSize: 12,
            formatter: (p: { name: string; value: number; percent: number }) => (p.value ? `${p.name}\n${formatCount(p.value)} (${p.percent.toFixed(0)}%)` : ""),
          },
          labelLine: { length: 8, length2: 8 },
          emphasis: { scale: true, scaleSize: 4 },
          data: rows.map((r, i) => ({ name: r.name, value: r.hotoPendingBlocks, itemStyle: { color: colors[i % colors.length] } })),
        },
      ],
    };
  }, [rows, t]);

  /* ---------- 4. GP-wise and block-wise >98% ---------- */
  const gp98Pct = rows.map((r) => share(r.gpsAbove98, r.reportingGps));
  const blk98Pct = rows.map((r) => share(r.blocksAbove98, r.reportingBlocks));
  const gp98Top = leader(gp98Pct);
  const blk98Top = leader(blk98Pct);
  const avOption = useMemo(
    () =>
      comparisonOption(
        t,
        names,
        [
          { name: `GPs >${H}%`, data: gp98Pct.map((v) => (v == null ? null : Number(v.toFixed(1)))), color: t.series[0] },
          { name: `Blocks >${H}%`, data: blk98Pct.map((v) => (v == null ? null : Number(v.toFixed(1)))), color: t.series[2] },
        ],
        "percent",
        [
          { labels: (i) => `${pctText(gp98Pct[i])} · ${formatCount(rows[i].gpsAbove98)} GPs` },
          { labels: (i) => `${pctText(blk98Pct[i])} · ${formatCount(rows[i].blocksAbove98)} blocks` },
        ],
        1,
        true,
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, t],
  );

  /* ---------- 5. GPs at 0% ---------- */
  const zeroPct = rows.map((r) => share(r.gpsAtZero, r.reportingGps));
  const zeroTop = leader(rows.map((r) => r.gpsAtZero));
  // Line (area) chart: one point per state; the state needing most attention gets a larger red point.
  const zeroOption = useMemo<EChartsOption>(
    () => ({
      animationDuration: 500,
      grid: { left: 4, right: 24, top: 28, bottom: 4, containLabel: true },
      tooltip: {
        trigger: "axis",
        textStyle: { fontFamily: t.font, fontSize: 12 },
        formatter: (ps: { dataIndex: number }[]) => {
          const r = rows[ps[0]?.dataIndex ?? -1];
          return r ? `${r.name}<br/><b>${formatCount(r.gpsAtZero)}</b> GPs at 0% (${pctText(share(r.gpsAtZero, r.reportingGps))} of reporting)<br/>No data (NA): ${formatCount(r.naGps)}` : "";
        },
      },
      xAxis: {
        type: "category",
        boundaryGap: true,
        data: names,
        axisTick: { show: false },
        axisLine: { lineStyle: { color: t.axis } },
        axisLabel: { color: t.muted, fontSize: 11, fontFamily: t.font },
      },
      yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid, type: [4, 4] } }, axisLabel: { color: t.muted, fontSize: 11, fontFamily: t.font } },
      series: [
        {
          type: "line",
          name: "GPs at 0%",
          smooth: 0.3,
          symbol: "circle",
          symbolSize: 9,
          lineStyle: { width: 2.5, color: t.serious },
          itemStyle: { color: t.serious, borderColor: t.surface, borderWidth: 2 },
          areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${t.serious}55` }, { offset: 1, color: `${t.serious}05` }] } },
          label: {
            show: true,
            position: "top",
            color: t.text,
            fontSize: 11,
            fontFamily: t.font,
            formatter: (p: { dataIndex: number }) => `${formatCount(rows[p.dataIndex].gpsAtZero)} · ${pctText(zeroPct[p.dataIndex])}`,
          },
          data: rows.map((r, i) => (i === zeroTop ? { value: r.gpsAtZero, symbolSize: 14, itemStyle: { color: t.critical, borderColor: t.surface, borderWidth: 2 } } : r.gpsAtZero)),
        },
      ],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, t],
  );

  /* ---------- 6. Penalty (<90%) ---------- */
  const belowPct = rows.map((r) => share(r.gpsBelowPenalty, r.reportingGps));
  const belowTop = leader(rows.map((r) => r.gpsBelowPenalty));
  // Rose chart: slice radius and angle grow with the GPs below 90%; labels give the count and the state's own share.
  const penaltyOption = useMemo<EChartsOption>(
    () => ({
      animationDuration: 500,
      tooltip: {
        trigger: "item",
        textStyle: { fontFamily: t.font, fontSize: 12 },
        formatter: (p: { dataIndex: number }) => {
          const r = rows[p.dataIndex];
          return r ? `${r.name}<br/><b>${formatCount(r.gpsBelowPenalty)}</b> GPs below ${P}% (${pctText(belowPct[p.dataIndex])} of reporting)<br/>Blocks below ${P}%: ${formatCount(r.penaltyBlocks)}` : "";
        },
      },
      series: [
        {
          type: "pie",
          roseType: "radius",
          radius: ["18%", "72%"],
          center: ["50%", "52%"],
          itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 },
          label: {
            color: t.text,
            fontSize: 11,
            fontFamily: t.font,
            formatter: (p: { dataIndex: number }) => `${rows[p.dataIndex].name}\n${formatCount(rows[p.dataIndex].gpsBelowPenalty)} · ${pctText(belowPct[p.dataIndex])}`,
          },
          labelLine: { length: 6, length2: 6 },
          data: rows.map((r, i) => ({
            name: r.name,
            value: r.gpsBelowPenalty,
            itemStyle: { color: i === belowTop ? t.critical : [t.series[0], t.warning, t.serious, t.series[4]][i % 4] },
          })),
        },
      ],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, t],
  );

  const pick = (i: number | null) => (i == null ? null : rows[i]);
  const tables = {
    nonAmc: [
      { key: "name", header: "State", render: (r) => r.name },
      { key: "rev", header: "Revised GPs", numeric: true, render: (r) => formatCount(r.revisedExisting) },
      { key: "amc", header: "AMC GPs", numeric: true, render: (r) => formatCount(r.amcGps) },
      { key: "non", header: "Non-AMC GPs", numeric: true, render: (r) => formatCount(r.nonAmcGps) },
    ] as SummaryColumn<Row>[],
    av: [
      { key: "name", header: "State", render: (r) => r.name },
      { key: "rg", header: "Reporting GPs", numeric: true, render: (r) => formatCount(r.reportingGps) },
      { key: "g98", header: `GPs >${H}%`, numeric: true, render: (r) => formatCount(r.gpsAbove98) },
      { key: "gp", header: "% of GPs", numeric: true, render: (r) => pctText(share(r.gpsAbove98, r.reportingGps)) },
      { key: "rb", header: "Reporting blocks", numeric: true, render: (r) => formatCount(r.reportingBlocks) },
      { key: "b98", header: `Blocks >${H}%`, numeric: true, render: (r) => formatCount(r.blocksAbove98) },
      { key: "bp", header: "% of blocks", numeric: true, render: (r) => pctText(share(r.blocksAbove98, r.reportingBlocks)) },
    ] as SummaryColumn<Row>[],
    zero: [
      { key: "name", header: "State", render: (r) => r.name },
      { key: "rg", header: "Reporting GPs", numeric: true, render: (r) => formatCount(r.reportingGps) },
      { key: "zero", header: "0% GPs", numeric: true, render: (r) => formatCount(r.gpsAtZero) },
      { key: "pct", header: "% at 0%", numeric: true, render: (r) => pctText(share(r.gpsAtZero, r.reportingGps)) },
      { key: "na", header: "NA", numeric: true, render: (r) => formatCount(r.naGps) },
    ] as SummaryColumn<Row>[],
    penalty: [
      { key: "name", header: "State", render: (r) => r.name },
      { key: "rg", header: "Reporting GPs", numeric: true, render: (r) => formatCount(r.reportingGps) },
      { key: "below", header: `GPs <${P}%`, numeric: true, render: (r) => formatCount(r.gpsBelowPenalty) },
      { key: "pct", header: `% <${P}%`, numeric: true, render: (r) => pctText(share(r.gpsBelowPenalty, r.reportingGps)) },
      { key: "blk", header: `Blocks <${P}%`, numeric: true, render: (r) => formatCount(r.penaltyBlocks) },
    ] as SummaryColumn<Row>[],
  };

  return (
    <div className="space-y-4">
      {/* ---------- 7. Summary KPIs (all three states) – small tiles ---------- */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        <MiniKpi
          loading={loading || !s}
          icon={ShieldOff}
          color="var(--na)"
          label="Non-AMC GPs"
          info="Revised existing GPs (not converted to NP / closed) that are not under AMC on the reporting week end."
          value={formatCount(s?.nonAmcGps)}
          caption={s ? `AMC ${formatCount(s.amcGps)} of ${formatCount(s.revisedExisting)}` : undefined}
        />
        <MiniKpi
          loading={loading || !s}
          icon={Clock}
          color="var(--warning)"
          label="HOTO Pending Blocks"
          info="Unique blocks without any GP whose HOTO date is on or before the reporting week end (blocks, not GPs)."
          value={formatCount(s?.hotoPendingBlocks)}
          caption={s ? `of ${formatCount(s.blocks)} blocks` : undefined}
        />
        <MiniKpi
          loading={loading || !s}
          icon={Activity}
          color="var(--good)"
          label={`GPs >${H}%`}
          info={`AMC GPs with month-to-date availability above ${H}% (exactly ${H}% is not counted, as in the O&M sheet).`}
          value={formatCount(s?.gpsAbove98)}
          caption={s ? `${pctText(share(s.gpsAbove98, s.reportingGps))} of reporting GPs` : undefined}
        />
        <MiniKpi
          loading={loading || !s}
          icon={Boxes}
          color="var(--series-3)"
          label={`Blocks >${H}%`}
          info={`Blocks whose mean MTD availability of their AMC GPs is above ${H}% – the block-level metric, not "one GP above ${H}%".`}
          value={formatCount(s?.blocksAbove98)}
          caption={s ? `${pctText(share(s.blocksAbove98, s.reportingBlocks))} of reporting blocks` : undefined}
        />
        <MiniKpi
          loading={loading || !s}
          icon={Ban}
          color="var(--critical)"
          label="GPs at 0%"
          info="AMC GPs with exactly 0% month-to-date availability. GPs without data (NA) are counted separately, never as 0%."
          value={formatCount(s?.gpsAtZero)}
          caption={s ? `NA (no data) ${formatCount(s.naGps)}` : undefined}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* ---------- 2. Non-AMC ---------- */}
        <ChartCard
          title="Non-AMC GPs by State"
          description="Revised existing GPs not under AMC · click a bar or row for the GPs"
          period={period}
          actions={<Leader label="Highest" row={pick(nonAmcTop)} value={nonAmcTop != null ? formatCount(rows[nonAmcTop].nonAmcGps) : undefined} />}
          loading={loading}
          empty={empty}
          height={210}
        >
          <EChart option={nonAmcOption} height={210} ariaLabel="Non-AMC GPs by state" onClick={onBar((id) => openList(id, "non-amc-gps"))} />
          <div className="mt-3">
            <CompactTable
              columns={tables.nonAmc}
              rows={rows}
              total={{ name: "Total", rev: formatCount(sum(rows, (r) => r.revisedExisting)), amc: formatCount(sum(rows, (r) => r.amcGps)), non: formatCount(sum(rows, (r) => r.nonAmcGps)) }}
              rowKey={(r) => r.id}
              onRowClick={(r) => openList(r.id, "non-amc-gps")}
              rowLabel={(r) => `Open the Non-AMC GPs of ${r.name}`}
              caption="Non-AMC GPs by state"
            />
          </div>
        </ChartCard>

        {/* ---------- 3. HOTO pending blocks ---------- */}
        <ChartCard
          title="HOTO Pending Blocks by State"
          description="Unique blocks where HOTO is not done · click a slice or state for the blocks"
          period={data?.asOf ? `As of ${formatDate(data.asOf)}` : undefined}
          actions={<Leader label="Most pending" row={pick(hotoTop)} value={hotoTop != null ? formatCount(rows[hotoTop].hotoPendingBlocks) : undefined} />}
          loading={loading}
          empty={empty}
          height={260}
        >
          {hotoPendingTotal === 0 ? (
            <p className="flex h-[190px] items-center justify-center text-sm font-medium text-good-text">HOTO is done in every block – no pending blocks.</p>
          ) : (
            <div className="relative mx-auto max-w-[340px]">
              <EChart
                option={hotoOption}
                height={190}
                ariaLabel="HOTO pending blocks by state (donut)"
                onClick={onBar((id) => openGroup(id, "hotoBlocks", "hoto-pending-blocks"))}
              />
              {/* Total in the donut hole */}
              <div className="pointer-events-none absolute inset-x-0 top-1/2 -translate-y-1/2 text-center" aria-hidden>
                <p className="tabular text-[20px] font-bold leading-none text-heading">{formatCount(hotoPendingTotal)}</p>
                <p className="mt-0.5 text-[10.5px] text-muted-foreground">pending</p>
              </div>
            </div>
          )}
          {/* Plain summary instead of a table: one line per state */}
          <ul className="mt-3 divide-y divide-border/70 rounded-lg border border-border text-[13px]">
            {rows.map((r, i) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => openGroup(r.id, "hotoBlocks", "hoto-pending-blocks")}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-primary-soft/50 focus-visible:bg-accent focus-visible:outline-none"
                >
                  <span className="flex items-center gap-2 font-medium">
                    <span className="size-2.5 rounded-full" style={{ background: [t.series[0], t.series[1], t.series[2], t.series[4]][i % 4] }} aria-hidden />
                    {r.name}
                  </span>
                  <span className="text-muted-foreground">
                    <b className={cn("tabular text-heading", r.hotoPendingBlocks > 0 && "text-critical-text")}>{formatCount(r.hotoPendingBlocks)}</b> pending HOTO blocks
                    <span className="ml-1 text-subtle-foreground">of {formatCount(r.blocks)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </ChartCard>
      </div>

      {/* ---------- 4. >98% GP-wise and block-wise ---------- */}
      <ChartCard
        title={`GP-wise and Block-wise Availability >${H}%`}
        description={`% of reporting AMC GPs and of reporting blocks above ${H}% (block = mean of its AMC GPs) · click a bar or row`}
        period={period}
        info={`Exactly ${H}% is not counted (O&M sheet rule). Block-wise uses the block's mean AMC GP availability, so a block does not qualify just because one GP is above ${H}%. GPs / blocks without data are left out of the percentage.`}
        actions={
          <div className="flex flex-wrap justify-end gap-1.5">
            <Leader label="Best GP %" tone="good" row={pick(gp98Top)} value={gp98Top != null ? pctText(gp98Pct[gp98Top]) : undefined} />
            <Leader label="Best block %" tone="good" row={pick(blk98Top)} value={blk98Top != null ? pctText(blk98Pct[blk98Top]) : undefined} />
          </div>
        }
        loading={loading}
        empty={empty}
        height={260}
      >
        <div className="grid grid-cols-1 items-center gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          <EChart option={avOption} height={260} ariaLabel={`GPs and blocks above ${H}% by state`} onClick={onBar((id) => openGroup(id, "health", "gps-above-98"))} />
          <CompactTable
            columns={tables.av}
            rows={rows}
            total={{
              name: "Total",
              rg: formatCount(sum(rows, (r) => r.reportingGps)),
              g98: formatCount(sum(rows, (r) => r.gpsAbove98)),
              gp: pctText(share(sum(rows, (r) => r.gpsAbove98), sum(rows, (r) => r.reportingGps))),
              rb: formatCount(sum(rows, (r) => r.reportingBlocks)),
              b98: formatCount(sum(rows, (r) => r.blocksAbove98)),
              bp: pctText(share(sum(rows, (r) => r.blocksAbove98), sum(rows, (r) => r.reportingBlocks))),
            }}
            rowKey={(r) => r.id}
            onRowClick={(r) => openGroup(r.id, "health", "gps-above-98")}
            rowLabel={(r) => `Open the GPs above ${H}% of ${r.name}`}
            caption={`GPs and blocks above ${H}% by state`}
          />
        </div>
      </ChartCard>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* ---------- 5. 0% GPs ---------- */}
        <ChartCard
          title="GPs at 0% Availability by State"
          description="AMC GPs at exactly 0% MTD (no-data GPs counted apart) · click a point or row"
          period={period}
          actions={<Leader label="Needs most attention" row={pick(zeroTop)} value={zeroTop != null ? formatCount(rows[zeroTop].gpsAtZero) : undefined} />}
          loading={loading}
          empty={empty}
          height={210}
        >
          <EChart option={zeroOption} height={210} ariaLabel="GPs at 0% by state" onClick={onBar((id) => openGroup(id, "health", "gps-at-zero"))} />
          <div className="mt-3">
            <CompactTable
              columns={tables.zero}
              rows={rows}
              total={{
                name: "Total",
                rg: formatCount(sum(rows, (r) => r.reportingGps)),
                zero: formatCount(sum(rows, (r) => r.gpsAtZero)),
                pct: pctText(share(sum(rows, (r) => r.gpsAtZero), sum(rows, (r) => r.reportingGps))),
                na: formatCount(sum(rows, (r) => r.naGps)),
              }}
              rowKey={(r) => r.id}
              onRowClick={(r) => openGroup(r.id, "health", "gps-at-zero")}
              rowLabel={(r) => `Open the 0% GPs of ${r.name}`}
              caption="GPs at 0% by state"
            />
          </div>
        </ChartCard>

        {/* ---------- 6. Penalty ---------- */}
        <ChartCard
          title={`Penalty Analysis – GPs below ${P}%`}
          description={`AMC GPs below ${P}% MTD (0% included) · click a slice or row for the blocks`}
          period={period}
          actions={<Leader label="Highest" row={pick(belowTop)} value={belowTop != null ? formatCount(rows[belowTop].gpsBelowPenalty) : undefined} />}
          loading={loading}
          empty={empty}
          height={210}
        >
          <EChart option={penaltyOption} height={210} ariaLabel={`GPs below ${P}% by state`} onClick={onBar((id) => openGroup(id, "health", "penalty-blocks"))} />
          <div className="mt-3">
            <CompactTable
              columns={tables.penalty}
              rows={rows}
              total={{
                name: "Total",
                rg: formatCount(sum(rows, (r) => r.reportingGps)),
                below: formatCount(sum(rows, (r) => r.gpsBelowPenalty)),
                pct: pctText(share(sum(rows, (r) => r.gpsBelowPenalty), sum(rows, (r) => r.reportingGps))),
                blk: formatCount(sum(rows, (r) => r.penaltyBlocks)),
              }}
              rowKey={(r) => r.id}
              onRowClick={(r) => openGroup(r.id, "health", "penalty-blocks")}
              rowLabel={(r) => `Open the penalty-prone blocks of ${r.name}`}
              caption={`GPs below ${P}% by state`}
            />
          </div>
        </ChartCard>
      </div>
    </div>
  );
}
