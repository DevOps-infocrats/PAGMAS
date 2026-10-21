"use client";

import { useMemo, useState } from "react";
import { BAND_COLORS, trendLineOption } from "@/components/charts/builders";
import { ChartCard } from "@/components/charts/chart-card";
import { EChart } from "@/components/charts/echart";
import { useChartTheme } from "@/components/charts/use-chart-theme";
import { Segmented } from "@/components/ui/controls";
import { Select } from "@/components/ui/overlays";
import {
  FlipButton,
  PeriodGrid,
} from "@/features/circle-insights/circle-charts";
import type { BlockInsightsResponse, BlockUptimeColumn } from "@/lib/api";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatPercent } from "@/lib/utils/format";

type Data = BlockInsightsResponse | undefined;

function Labeled({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

/* ------------------------------------------------------------------ GP uptime */

type UptimeView = "periods" | "daily";
type GraphView = "week" | "month" | "day";

/**
 * GP Uptime Performance of one block – the same report table as Circle Insights:
 * availability bands × months / month-to-date / weeks (or the days of the current week),
 * with the arrow on the right flipping to a line graph of any band.
 */
export function BlockUptimeSection({
  data,
  loading,
}: {
  data: Data;
  loading: boolean;
}) {
  const t = useChartTheme();
  const u = data?.gpUptime;
  const [view, setView] = useState<UptimeView>("periods");
  const [graph, setGraph] = useState(false);
  const [gView, setGView] = useState<GraphView>("week");
  const [gShow, setGShow] = useState<string>("top");

  const all = useMemo(() => u?.columns ?? [], [u]);
  const bands = u?.bands?.length ? u.bands : Object.keys(BAND_COLORS);
  const top = bands[bands.length - 1];
  const healthy = u?.thresholds.healthy ?? THRESHOLDS.healthy;
  const penalty = u?.thresholds.penalty ?? THRESHOLDS.penalty;
  const currentWeek = all.find((c) => c.kind === "week");
  const weekLabel = currentWeek
    ? currentWeek.label.replace("Till ", "")
    : "current week";
  const blockName = data?.block.name ?? "";

  // Month & week table: months, month TD, then the weeks oldest → newest, labelled WK-nn
  // (e.g. WK-38 … WK-41). Built from the API columns, so new weeks appear automatically.
  const cols =
    view === "daily"
      ? all.filter((c) => c.kind === "day")
      : [
          ...all.filter((c) => c.kind !== "day" && c.kind !== "week"),
          ...all
            .filter((c) => c.kind === "week")
            .sort((a, b) => a.endDate.localeCompare(b.endDate))
            .map((c) => ({ ...c, label: `WK-${c.key.replace(/^W-/, "")}` })),
        ];
  const highlight =
    view === "periods"
      ? cols.findIndex((c) => c.kind === "mtd")
      : cols.length - 1;

  const bandUpper = (b: string) =>
    Number(
      b
        .replace(/[^0-9.–-]/g, "")
        .split(/[–-]/)
        .pop() || 0,
    );
  const penaltyBands = bands.filter(
    (b) => b !== top && bandUpper(b) <= penalty,
  );
  const showKey = gShow === "top" ? top : gShow;
  const showOptions = [
    ...[...bands]
      .reverse()
      .map((b) => ({ value: b === top ? "top" : b, label: b })),
    { value: "penalty", label: `Below ${penalty}% (penalty)` },
    { value: "avg", label: "Average availability" },
  ];

  const trend = useMemo(() => {
    const pts = all
      .filter((c) =>
        gView === "day"
          ? c.kind === "day"
          : gView === "week"
            ? c.kind === "week"
            : c.kind === "month" || c.kind === "mtd",
      )
      .sort((a, b) => a.endDate.localeCompare(b.endDate));
    const value = (c: BlockUptimeColumn): number | null =>
      showKey === "avg"
        ? c.average
        : showKey === "penalty"
          ? penaltyBands.reduce((s, b) => s + (c.counts[b] ?? 0), 0)
          : (c.counts[showKey] ?? 0);
    return { labels: pts.map((c) => c.label), values: pts.map(value) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all, gView, showKey, penaltyBands.length]);

  const measureLabel =
    showKey === "avg"
      ? "Average availability"
      : showKey === "penalty"
        ? `AMC GPs below ${penalty}%`
        : `AMC GPs at ${showKey}`;
  const chartTitle = `${measureLabel} — ${gView === "day" ? `day by day (${weekLabel})` : gView === "week" ? "week by week" : "month by month"}`;
  const isPct = showKey === "avg";
  const lineColor =
    showKey === "avg"
      ? t.series[0]
      : showKey === "penalty"
        ? t.critical
        : showKey === top
          ? "#0b8fb3"
          : (BAND_COLORS[showKey] ?? t.series[0]);
  const option = useMemo(
    () =>
      trendLineOption({
        theme: t,
        categories: trend.labels,
        values: trend.values,
        name: measureLabel,
        unit: isPct ? "percent" : "count",
        color: lineColor,
      }),
    [t, trend, measureLabel, isPct, lineColor],
  );
  const known = trend.values.filter((v): v is number => v != null);
  const latest = known.at(-1) ?? null;
  const change =
    known.length >= 2
      ? known[known.length - 1] - known[known.length - 2]
      : null;
  // A rise is good for >98%, 95–98% and the average; bad for low bands / penalty.
  const riseIsGood =
    showKey === top || showKey === "avg" || showKey === "95–98%";

  const rows = [...bands].reverse().map((b) => ({
    key: b,
    label: (
      <span className="inline-flex items-center gap-2">
        <span
          className="size-2.5 shrink-0 rounded-sm"
          style={{ background: BAND_COLORS[b] }}
          aria-hidden
        />
        {b}
      </span>
    ),
    cells: cols.map((c) => formatCount(c.counts[b] ?? 0)),
  }));
  const footer = [
    {
      key: "tot",
      label: "Total with value",
      cells: cols.map((c) => formatCount(c.reported)),
    },
    {
      key: "na",
      label: "Not reported (NA)",
      cells: cols.map((c) => formatCount(c.na)),
    },
    {
      key: "all",
      label: "Total AMC GPs",
      cells: cols.map((c) => formatCount(c.amcGps)),
    },
    {
      key: "avg",
      label: "Block availability",
      cells: cols.map((c) => formatPercent(c.average, 2)),
    },
  ];

  const anyAmc = all.some((c) => c.amcGps > 0);
  const title = `GP Uptime Performance (AMC GPs) — ${blockName}`;
  const description =
    view === "daily" && !graph
      ? `How many AMC GPs of this block fall in each availability band on every day of ${weekLabel}`
      : "How many AMC / incremental GPs of this block fall in each availability band, month-wise and week-wise";

  return (
    <ChartCard
      title={title}
      description={description}
      info={`Months = each GP's monthly AMC availability (GP Wise Data); TD = month-to-date average of daily values from the later of the month start and the AMC date; weeks = the weekly W-nn columns; days = that day's value. A GP is counted from its AMC date. Bands follow the workbook: 0%, then lower ≤ value < upper; the top band is strictly above ${healthy}% (exactly ${healthy}% stays in 95–${healthy}%). Block availability = average of its AMC GPs. NA = AMC GP with no value – never counted as 0%.`}
      loading={loading}
      empty={!loading && (!u || !anyAmc)}
      emptyMessage={
        !u
          ? "GP-wise uptime is available with the live backend only."
          : "No GP of this block is under AMC yet – uptime is tracked from each GP's AMC date."
      }
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
        <div
          key="graph"
          className="flip-in rounded-xl border border-border bg-gradient-to-b from-muted/40 to-transparent p-4"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h4 className="text-[15px] font-semibold">{chartTitle}</h4>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {known.length ? (
                  <>
                    Latest{" "}
                    <b className="text-foreground">
                      {isPct ? formatPercent(latest, 2) : formatCount(latest)}
                    </b>
                    {change != null && (
                      <span
                        className={cn(
                          "ml-2 rounded px-1.5 py-0.5 font-medium",
                          change === 0
                            ? "bg-muted text-muted-foreground"
                            : change > 0 === riseIsGood
                              ? "bg-good-soft text-good-text"
                              : "bg-critical-soft text-critical-text",
                        )}
                      >
                        {change > 0 ? "▲ +" : change < 0 ? "▼ −" : "± "}
                        {isPct
                          ? `${Math.abs(change).toFixed(2)} pp`
                          : formatCount(Math.abs(change))}{" "}
                        vs previous
                      </span>
                    )}
                  </>
                ) : (
                  "No data for this selection"
                )}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Labeled label="View">
                <Select
                  ariaLabel="Graph columns"
                  className="h-8 w-36 border-0 px-2 font-medium"
                  value={gView}
                  onValueChange={(v) => setGView(v as GraphView)}
                  options={[
                    { value: "week", label: "Week" },
                    { value: "month", label: "Month" },
                    { value: "day", label: `Day · ${weekLabel}` },
                  ]}
                />
              </Labeled>
              <Labeled label="Show">
                <Select
                  ariaLabel="Graph measure"
                  className="h-8 w-52 border-0 px-2 font-medium"
                  value={gShow}
                  onValueChange={setGShow}
                  options={showOptions}
                />
              </Labeled>
            </div>
          </div>
          <EChart option={option} height={330} ariaLabel={chartTitle} />
        </div>
      ) : (
        <div key={`table-${view}`} className="flip-in">
          <PeriodGrid
            caption={title}
            corner="GP Uptime Performance (AMC GPs)"
            periods={cols}
            rows={rows}
            footer={footer}
            highlight={highlight}
          />
        </div>
      )}
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ OLT distribution */

const escHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

/**
 * GPs per OLT location of one block: one bar per OLT (biggest first), labelled with the
 * GP count and its share of the block. GPs whose OLT is blank / "-" in GP Wise Data are
 * shown last, in grey, as "OLT not recorded".
 */
export function OltDistribution({
  data,
  loading,
}: {
  data: Data;
  loading: boolean;
}) {
  const t = useChartTheme();
  const gps = useMemo(() => data?.gps ?? [], [data]);

  const olts = useMemo(() => {
    const by = new Map<string, { location: string; names: string[] }>();
    for (const g of gps) {
      const key = g.oltId ?? "~none";
      const row = by.get(key) ?? {
        location: g.oltLocation ?? "OLT not recorded",
        names: [],
      };
      row.names.push(g.name);
      by.set(key, row);
    }
    return [...by.entries()]
      .map(([key, r]) => ({
        key,
        location: r.location,
        names: r.names.sort((a, b) => a.localeCompare(b)),
        count: r.names.length,
      }))
      .sort(
        (a, b) =>
          Number(a.key === "~none") - Number(b.key === "~none") ||
          b.count - a.count ||
          a.location.localeCompare(b.location),
      );
  }, [gps]);

  const total = gps.length;
  const recorded = olts.filter((o) => o.key !== "~none");
  const unrecorded = total - recorded.reduce((s, o) => s + o.count, 0);
  const share = (n: number) =>
    total ? `${Math.round((n / total) * 100)}%` : "–";

  const option = useMemo(
    () => ({
      animationDuration: 500,
      grid: { left: 8, right: 96, top: 4, bottom: 4, containLabel: true },
      tooltip: {
        trigger: "item",
        confine: true,
        backgroundColor: t.surface,
        borderColor: t.border,
        borderWidth: 1,
        padding: [8, 12],
        textStyle: { color: t.text, fontSize: 12, fontFamily: t.font },
        extraCssText:
          "box-shadow:0 8px 24px rgba(15,23,42,.12);border-radius:8px;max-width:320px;white-space:normal;",
        formatter: (p: { dataIndex: number }) => {
          const o = olts[p.dataIndex];
          if (!o) return "";
          const names =
            o.names.slice(0, 12).map(escHtml).join(", ") +
            (o.names.length > 12 ? ` +${o.names.length - 12} more` : "");
          return `<div style="font-weight:600;margin-bottom:2px">${escHtml(o.location)}</div><div><b>${o.count}</b> GP${o.count === 1 ? "" : "s"} · ${share(o.count)} of the block</div><div style="margin-top:4px;color:${t.muted}">${names}</div>`;
        },
      },
      xAxis: {
        type: "value",
        minInterval: 1,
        splitLine: { lineStyle: { color: t.grid } },
        axisLabel: { color: t.muted, fontSize: 11, fontFamily: t.font },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: olts.map((o) => o.location),
        axisTick: { show: false },
        axisLine: { lineStyle: { color: t.axis } },
        axisLabel: {
          color: t.text,
          fontSize: 12,
          fontFamily: t.font,
          width: 140,
          overflow: "truncate",
        },
      },
      series: [
        {
          type: "bar",
          name: "GPs",
          barMaxWidth: 22,
          data: olts.map((o) => ({
            value: o.count,
            itemStyle: {
              color: o.key === "~none" ? t.na : t.series[0],
              borderRadius: [0, 4, 4, 0],
            },
          })),
          label: {
            show: true,
            position: "right",
            distance: 8,
            color: t.text,
            fontSize: 12,
            fontFamily: t.font,
            formatter: (p: { value: number }) =>
              `{b|${p.value} GP${p.value === 1 ? "" : "s"}}  {s|${share(p.value)}}`,
            rich: {
              b: { fontWeight: 600, color: t.text, fontSize: 12 },
              s: { color: t.muted, fontSize: 11 },
            },
          },
        },
      ],
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [olts, t, total],
  );

  const blockName = data?.block.name ?? "";
  const description =
    recorded.length === 0
      ? "No OLT location is recorded for this block's GPs in GP Wise Data"
      : `${total} GPs connected through ${recorded.length} OLT location${recorded.length === 1 ? "" : "s"}${unrecorded ? ` · ${unrecorded} GP${unrecorded === 1 ? "" : "s"} without an OLT recorded` : ""}`;

  return (
    <ChartCard
      title={`OLT Distribution — ${blockName}`}
      description={description}
      info="Each GP is counted once, under the OLT location recorded for it in GP Wise Data. Bar = number of GPs on that OLT; % = share of all GPs in the block. Grey = GPs whose OLT location is blank or '-' in the source. Hover a bar to see its GPs."
      loading={loading}
      empty={!loading && total === 0}
      height={220}
    >
      <div className="px-1">
        <EChart
          option={option}
          height={Math.max(140, olts.length * 42 + 24)}
          ariaLabel={`Number of GPs per OLT location in ${blockName}`}
        />
        <p className="mt-2 text-xs text-subtle-foreground">
          Biggest OLT first · hover a bar to see the GPs it serves
        </p>
      </div>
    </ChartCard>
  );
}
