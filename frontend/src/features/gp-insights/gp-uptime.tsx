"use client";

import { useMemo, useState } from "react";
import { BAND_COLORS } from "@/components/charts/builders";
import { ChartCard } from "@/components/charts/chart-card";
import { EChart, type EChartsOption } from "@/components/charts/echart";
import {
  useChartTheme,
  type ChartTheme,
} from "@/components/charts/use-chart-theme";
import { Segmented } from "@/components/ui/controls";
import { Select } from "@/components/ui/overlays";
import {
  FlipButton,
  PeriodGrid,
} from "@/features/circle-insights/circle-charts";
import type { GpUptime, GpUptimeColumn } from "@/lib/api";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatDate, formatPercent } from "@/lib/utils/format";

type TableView = "periods" | "daily";
type GraphView = "week" | "month" | "day";
type Tone = "good" | "warning" | "critical";

const num = (v: GpUptimeColumn["value"]): number | null =>
  typeof v === "number" ? v : null;
const esc = (s: string) =>
  s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function toneOf(v: number, healthy: number, penalty: number): Tone {
  return v > healthy ? "good" : v >= penalty ? "warning" : "critical";
}
const TONE_TEXT: Record<Tone, string> = {
  good: "text-good-text",
  warning: "text-warning-text",
  critical: "text-critical-text",
};

/** GP line (solid, labelled) against its block's line (dashed) with the penalty reference. */
function gpTrendOption(
  t: ChartTheme,
  labels: string[],
  gp: (number | null)[],
  block: (number | null)[],
  gpName: string,
  penalty: number,
): EChartsOption {
  const all = [...gp, ...block].filter((v): v is number => v != null);
  const lo = all.length ? Math.min(...all, penalty) : penalty;
  const c = "#0b8fb3";
  return {
    animationDuration: 600,
    grid: { left: 8, right: 28, top: 40, bottom: 8, containLabel: true },
    legend: {
      top: 0,
      right: 0,
      icon: "roundRect",
      itemWidth: 14,
      itemHeight: 3,
      textStyle: { color: t.muted, fontSize: 12, fontFamily: t.font },
    },
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: t.surface,
      borderColor: t.border,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: t.text, fontSize: 12, fontFamily: t.font },
      extraCssText:
        "box-shadow:0 8px 24px rgba(15,23,42,.12);border-radius:8px;",
      axisPointer: { type: "line", lineStyle: { color: t.axis } },
      formatter: (raw: unknown) => {
        const ps = raw as {
          axisValue: string;
          marker: string;
          seriesName: string;
          value: unknown;
        }[];
        if (!ps.length) return "";
        const rows = ps
          .map((p) => {
            const v =
              p.value == null || p.value === "-"
                ? "NA"
                : formatPercent(Number(p.value), 2);
            return `<div style="display:flex;justify-content:space-between;gap:16px"><span>${p.marker}${esc(p.seriesName)}</span><b style="font-variant-numeric:tabular-nums">${v}</b></div>`;
          })
          .join("");
        return `<div style="font-weight:600;margin-bottom:4px">${esc(ps[0].axisValue)}</div>${rows}`;
      },
    },
    xAxis: {
      type: "category",
      data: labels,
      boundaryGap: true,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: t.axis } },
      axisLabel: {
        color: t.muted,
        fontSize: 12,
        fontFamily: t.font,
        hideOverlap: true,
      },
    },
    yAxis: {
      type: "value",
      min: Math.max(0, Math.floor((lo - 5) / 5) * 5),
      max: 100,
      splitLine: { lineStyle: { color: t.grid, type: [4, 4] } },
      axisLabel: {
        color: t.muted,
        fontSize: 11,
        fontFamily: t.font,
        formatter: (v: number) => `${v}%`,
      },
    },
    series: [
      {
        type: "line",
        name: gpName,
        data: gp.map((v) => (v == null ? "-" : v)),
        smooth: 0.35,
        connectNulls: false,
        symbol: "circle",
        symbolSize: 9,
        z: 3,
        lineStyle: { width: 3, color: c, cap: "round", join: "round" },
        itemStyle: { color: c, borderColor: t.surface, borderWidth: 2 },
        label: {
          show: true,
          position: "top",
          distance: 8,
          color: t.text,
          fontSize: 12,
          fontWeight: 600,
          fontFamily: t.font,
          formatter: (p: { value: unknown }) =>
            p.value == null || p.value === "-"
              ? ""
              : formatPercent(Number(p.value), 2),
        },
        areaStyle: {
          color: {
            type: "linear",
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: `${c}33` },
              { offset: 1, color: `${c}00` },
            ],
          },
        },
        markLine: {
          symbol: "none",
          silent: true,
          data: [{ yAxis: penalty }],
          lineStyle: { color: t.critical, type: "dashed", width: 1.5 },
          label: {
            formatter: `${penalty}% penalty line`,
            color: t.critical,
            fontSize: 11,
            fontWeight: 600,
            position: "insideEndTop",
          },
        },
      },
      {
        type: "line",
        name: "Block average",
        data: block.map((v) => (v == null ? "-" : v)),
        smooth: 0.35,
        connectNulls: false,
        symbol: "circle",
        symbolSize: 6,
        lineStyle: { width: 2, color: t.muted, type: "dashed" },
        itemStyle: { color: t.muted, borderColor: t.surface, borderWidth: 1 },
      },
    ],
  };
}

/**
 * GP Uptime Performance of one GP – the same period structure as the circle and block tables
 * (months, month to date, weeks, or the days of the current week). For a single GP the rows are its
 * availability, band and status, with its block's value alongside for context.
 */
export function GpUptimeSection({
  uptime,
  gpName,
  loading,
}: {
  uptime?: GpUptime;
  gpName: string;
  loading?: boolean;
}) {
  const t = useChartTheme();
  const [view, setView] = useState<TableView>("periods");
  const [graph, setGraph] = useState(false);
  const [gView, setGView] = useState<GraphView>("week");
  const all = useMemo(() => uptime?.columns ?? [], [uptime]);
  const healthy = uptime?.thresholds.healthy ?? THRESHOLDS.healthy;
  const penalty = uptime?.thresholds.penalty ?? THRESHOLDS.penalty;
  const currentWeek = all.find((c) => c.kind === "week");
  const weekLabel = currentWeek
    ? currentWeek.label.replace("Till ", "")
    : "current week";

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
  const underAmc = all.some((c) => c.value !== null);

  const cellValue = (c: GpUptimeColumn) =>
    c.value === null ? (
      <span
        key={c.key}
        className="text-subtle-foreground"
        title="Not under AMC in this period"
      >
        —
      </span>
    ) : c.value === "NA" ? (
      <span
        key={c.key}
        className="text-muted-foreground"
        title="Not reported (NA) – not 0%"
      >
        NA
      </span>
    ) : (
      <span
        key={c.key}
        className={cn(
          "font-semibold",
          TONE_TEXT[toneOf(c.value, healthy, penalty)],
        )}
      >
        {formatPercent(c.value, 2)}
      </span>
    );

  // Rows = availability bands (best first); each cell = days the GP spent in that band in the period.
  const bands = uptime?.bands?.length ? uptime.bands : Object.keys(BAND_COLORS);
  const dash = (c: GpUptimeColumn, title: string) => (
    <span key={c.key} className="text-subtle-foreground" title={title}>
      –
    </span>
  );
  const noDays = (c: GpUptimeColumn) =>
    c.value === null
      ? "Not under AMC in this period"
      : "Daily values are not in the workbook for this period";
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
    cells: cols.map((c) => {
      if (!c.days) return dash(c, noDays(c));
      const n = c.days.counts[b] ?? 0;
      return (
        <span
          key={c.key}
          className={
            n === 0 ? "text-subtle-foreground" : "font-semibold text-foreground"
          }
        >
          {n}
        </span>
      );
    }),
  }));
  const footer = [
    {
      key: "tot",
      label: "Total days with value",
      cells: cols.map((c) =>
        c.days ? String(c.days.reported) : dash(c, noDays(c)),
      ),
    },
    {
      key: "na",
      label: "Not reported (NA) days",
      cells: cols.map((c) => (c.days ? String(c.days.na) : dash(c, noDays(c)))),
    },
    { key: "gp", label: "GP availability", cells: cols.map(cellValue) },
    {
      key: "blk",
      label: "Block availability",
      cells: cols.map((c) => formatPercent(c.blockAverage, 2)),
    },
  ];
  const hasMissingDaily = cols.some((c) => c.value !== null && !c.days);

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
    return {
      labels: pts.map((c) => c.label),
      gp: pts.map((c) => num(c.value)),
      block: pts.map((c) => c.blockAverage),
    };
  }, [all, gView]);
  const option = useMemo(
    () =>
      gpTrendOption(t, trend.labels, trend.gp, trend.block, gpName, penalty),
    [t, trend, gpName, penalty],
  );
  const known = trend.gp.filter((v): v is number => v != null);
  const latest = known.at(-1) ?? null;
  const change =
    known.length >= 2
      ? known[known.length - 1] - known[known.length - 2]
      : null;
  const chartTitle = `Availability of ${gpName} — ${gView === "day" ? `day by day (${weekLabel})` : gView === "week" ? "week by week" : "month by month"}`;

  return (
    <ChartCard
      title={`GP Uptime Performance — ${gpName}`}
      description={
        view === "daily" && !graph
          ? `Which availability band this GP was in on every day of ${weekLabel}`
          : "How many days this GP spent in each availability band, month-wise and week-wise"
      }
      info={`Each cell = number of days the GP spent in that band during the period, counted from the daily sheet over the days it was under AMC (from its AMC date). GP availability: months = monthly AMC column (GP Wise Data), TD = month to date, weeks = weekly W-nn columns, days = that day's value. Bands: 0%, then lower ≤ value < upper; the top band is strictly above ${healthy}%. Block availability = average of the block's AMC GPs. NA = not reported – never counted as 0%.`}
      loading={loading}
      empty={!loading && (!uptime || !underAmc)}
      emptyMessage={
        !uptime
          ? "GP uptime is available with the live backend only."
          : "This GP is not under AMC yet – availability is tracked from its AMC date."
      }
      actions={
        <div className="flex flex-wrap items-center justify-end gap-2">
          {!graph && (
            <Segmented<TableView>
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
          className="flip-in rounded-lg border border-border bg-gradient-to-b from-muted/40 to-transparent p-4"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h4 className="text-[15px] font-bold text-subheading">{chartTitle}</h4>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {known.length ? (
                  <>
                    Latest{" "}
                    <b
                      className={cn(
                        latest != null &&
                          TONE_TEXT[toneOf(latest, healthy, penalty)],
                      )}
                    >
                      {formatPercent(latest, 2)}
                    </b>
                    {change != null && (
                      <span
                        className={cn(
                          "ml-2 rounded px-1.5 py-0.5 font-medium",
                          change === 0
                            ? "bg-muted"
                            : change > 0
                              ? "bg-good-soft text-good-text"
                              : "bg-critical-soft text-critical-text",
                        )}
                      >
                        {change > 0 ? "▲ +" : change < 0 ? "▼ −" : "± "}
                        {Math.abs(change).toFixed(2)} pp vs previous
                      </span>
                    )}
                  </>
                ) : (
                  "No values for this selection"
                )}
              </p>
            </div>
            <label className="flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1">
              <span className="text-xs text-muted-foreground">View</span>
              <Select
                ariaLabel="Graph columns"
                className="h-8 w-36 border-0 px-2 font-semibold shadow-none hover:bg-accent"
                value={gView}
                onValueChange={(v) => setGView(v as GraphView)}
                options={[
                  { value: "week", label: "Week" },
                  { value: "month", label: "Month" },
                  { value: "day", label: `Day · ${weekLabel}` },
                ]}
              />
            </label>
          </div>
          <EChart option={option} height={330} ariaLabel={chartTitle} />
        </div>
      ) : (
        <div key={`table-${view}`} className="flip-in">
          <PeriodGrid
            caption={`GP Uptime Performance — ${gpName}`}
            corner="Availability band (days)"
            periods={cols}
            rows={rows}
            footer={footer}
            highlight={highlight}
          />
          <p className="mt-2 px-1 text-xs text-subtle-foreground">
            Cells = number of days in each band · GP availability = the
            period&rsquo;s own value · NA = not reported (not 0%)
            {hasMissingDaily && uptime?.dailyFrom
              ? ` · – = no day counts: the workbook’s daily values start ${formatDate(uptime.dailyFrom)}`
              : ""}
          </p>
        </div>
      )}
    </ChartCard>
  );
}
