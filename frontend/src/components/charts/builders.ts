import { formatCount, formatPercent, formatShortDate, formatValue } from "@/lib/utils/format";
import type { MetricUnit } from "@/types";
import type { EChartsOption } from "./echart";
import type { ChartTheme } from "./use-chart-theme";

/*
 * Option builders: one place for chart styling (thin bars, 2px lines,
 * hairline grid, consistent tooltip). Pages pass data + theme only.
 */

export interface BarSeries {
  name: string;
  data: (number | null)[];
  color?: string;
  stack?: string;
}

export interface LineSeries {
  name: string;
  data: (number | null)[];
  color?: string;
}

const axisLabel = (t: ChartTheme) => ({ color: t.muted, fontSize: 11, fontFamily: t.font });

interface AxisParam {
  axisValue: string;
  marker: string;
  seriesName: string;
  value: unknown;
}

const escapeHtml = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function tooltip(t: ChartTheme, unit: MetricUnit, header: (axisValue: string) => string = (v) => v) {
  return {
    trigger: "axis" as const,
    formatter: (raw: unknown) => {
      const params = (Array.isArray(raw) ? raw : [raw]) as AxisParam[];
      if (!params.length) return "";
      const rows = params
        .map((p) => {
          const v = p.value == null || p.value === "-" ? "NA" : formatValue(Number(p.value), unit);
          return `<div style="display:flex;justify-content:space-between;gap:16px;align-items:center"><span>${p.marker}${escapeHtml(p.seriesName)}</span><b style="font-variant-numeric:tabular-nums">${v}</b></div>`;
        })
        .join("");
      return `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(header(params[0].axisValue))}</div>${rows}`;
    },
    confine: true,
    backgroundColor: t.surface,
    borderColor: t.border,
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: t.text, fontSize: 12, fontFamily: t.font },
    extraCssText: "box-shadow:0 8px 24px rgba(15,23,42,.12);border-radius:8px;",
    axisPointer: { type: "shadow", shadowStyle: { color: "rgba(127,127,127,0.08)" } },
  };
}

function legend(t: ChartTheme, show: boolean) {
  return {
    show,
    top: 0,
    left: 0,
    icon: "roundRect",
    itemWidth: 10,
    itemHeight: 10,
    itemGap: 16,
    textStyle: { color: t.muted, fontSize: 12, fontFamily: t.font },
  };
}

const compactAxis = (unit: MetricUnit) => (v: number) =>
  unit === "percent" ? `${v}%` : v >= 100000 ? `${(v / 100000).toFixed(1)}L` : v >= 10000 ? `${(v / 1000).toFixed(1)}k` : formatCount(v);

export function barOption({
  theme: t,
  categories,
  series,
  unit,
  horizontal = false,
  threshold,
  maxValue,
  labels = false,
  barMaxWidth = 24,
  compactLabels = false,
  legendRows = 1,
}: {
  theme: ChartTheme;
  categories: string[];
  series: BarSeries[];
  unit: MetricUnit;
  horizontal?: boolean;
  threshold?: { value: number; label: string };
  maxValue?: number;
  /** Show the value at the end of every bar (use for few categories only) */
  labels?: boolean;
  barMaxWidth?: number;
  /** Bar labels as 10.1k / 8.4k (exact values stay in the tooltip) – for grouped bars in a narrow card */
  compactLabels?: boolean;
  /** Lines the legend may wrap to in a narrow card; the plot starts below them so nothing overlaps */
  legendRows?: number;
}): EChartsOption {
  const stacked = series.some((s) => s.stack);
  const valueAxis = {
    type: "value",
    max: maxValue,
    splitLine: { lineStyle: { color: t.grid } },
    axisLabel: { ...axisLabel(t), formatter: compactAxis(unit) },
  };
  const categoryAxis = {
    type: "category",
    data: categories,
    axisTick: { show: false },
    axisLine: { lineStyle: { color: t.axis } },
    axisLabel: { ...axisLabel(t), hideOverlap: true, width: horizontal ? 110 : 80, overflow: "truncate", interval: horizontal ? 0 : "auto" },
    inverse: horizontal,
  };
  const radius = horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
  return {
    animationDuration: 500,
    grid: { left: 4, right: 16, top: series.length > 1 ? 36 + 32 * (Math.max(1, legendRows) - 1) : 12, bottom: 4, containLabel: true },
    tooltip: tooltip(t, unit),
    legend: legend(t, series.length > 1),
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? categoryAxis : valueAxis,
    series: series.map((s, i) => ({
      type: "bar",
      name: s.name,
      stack: s.stack,
      data: s.data.map((v) => (v == null ? "-" : v)),
      barMaxWidth,
      barGap: "15%",
      label: labels
        ? {
            show: true,
            position: horizontal ? "right" : "top",
            distance: 4,
            color: t.muted,
            fontSize: compactLabels ? 10 : 11,
            fontFamily: t.font,
            // Zero bars stay unlabeled (no visual clutter); exact zeros are in the table below.
            formatter: (p: { value: unknown }) => {
              if (p.value == null || p.value === "-" || Number(p.value) === 0) return "";
              const v = Number(p.value);
              if (compactLabels && unit !== "percent" && Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)}k`;
              return formatValue(v, unit === "rkm" ? "count" : unit);
            },
          }
        : undefined,
      itemStyle: {
        color: s.color ?? t.series[i % t.series.length],
        borderRadius: !stacked || i === series.length - 1 ? radius : 0,
        borderColor: stacked ? t.surface : undefined,
        borderWidth: stacked ? 1 : 0,
      },
      emphasis: { focus: "series" },
      markLine:
        threshold && i === 0
          ? {
              symbol: "none",
              silent: true,
              lineStyle: { color: t.critical, type: "solid", width: 1 },
              label: { formatter: threshold.label, color: t.muted, fontSize: 11, position: "insideEndTop" },
              data: [horizontal ? { xAxis: threshold.value } : { yAxis: threshold.value }],
            }
          : undefined,
    })),
  };
}

export function lineOption({
  theme: t,
  dates,
  series,
  unit,
  threshold,
}: {
  theme: ChartTheme;
  /** ISO reporting dates (week end) */
  dates: string[];
  series: LineSeries[];
  unit: MetricUnit;
  threshold?: { value: number; label: string };
}): EChartsOption {
  const values = series.flatMap((s) => s.data.filter((v): v is number => v != null));
  const min = values.length ? Math.min(...values) : 0;
  const yMin = unit === "percent" ? Math.max(0, Math.floor((Math.min(min, threshold?.value ?? min) - 3) / 5) * 5) : 0;
  return {
    animationDuration: 500,
    grid: { left: 4, right: 20, top: series.length > 1 ? 40 : 16, bottom: 4, containLabel: true },
    tooltip: {
      ...tooltip(t, unit, (d) => `Week ending ${formatShortDate(d)}`),
      axisPointer: { type: "line", lineStyle: { color: t.axis } },
    },
    legend: legend(t, series.length > 1),
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: dates,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: t.axis } },
      axisLabel: { ...axisLabel(t), formatter: (d: string) => formatShortDate(d), hideOverlap: true },
    },
    yAxis: {
      type: "value",
      // Counts use a scaled axis so week-to-week movement is visible; % keeps a 100% ceiling.
      // Percent: 100% ceiling. Counts: tight padded range so week-to-week movement is visible.
      min: unit === "percent" ? yMin : (v: { min: number; max: number }) => Math.max(0, Math.floor(v.min - Math.max((v.max - v.min) * 0.5, v.max * 0.02, 1))),
      max: unit === "percent" ? 100 : (v: { min: number; max: number }) => Math.ceil(v.max + Math.max((v.max - v.min) * 0.5, v.max * 0.02, 1)),
      splitLine: { lineStyle: { color: t.grid } },
      axisLabel: { ...axisLabel(t), formatter: compactAxis(unit) },
    },
    series: series.map((s, i) => ({
      type: "line",
      name: s.name,
      data: s.data.map((v) => (v == null ? "-" : v)),
      connectNulls: false,
      symbol: "circle",
      symbolSize: 8,
      showSymbol: dates.length <= 12,
      lineStyle: { width: 2, cap: "round", join: "round" },
      itemStyle: { color: s.color ?? t.series[i % t.series.length], borderColor: t.surface, borderWidth: 2 },
      emphasis: { focus: "series" },
      markLine:
        threshold && i === 0
          ? {
              symbol: "none",
              silent: true,
              lineStyle: { color: t.critical, type: "solid", width: 1 },
              label: { formatter: threshold.label, color: t.muted, fontSize: 11, position: "insideEndTop" },
              data: [{ yAxis: threshold.value }],
            }
          : undefined,
    })),
  };
}

/** Tooltip date header used by table views and captions. */
export const reportingDateLabel = (iso: string) => `Week ending ${formatShortDate(iso)}`;
export const pct = (v: number | null) => formatPercent(v);

/** Line chart over categories (e.g. districts) – several measures on one count axis. */
export function categoryLineOption({
  theme: t,
  categories,
  series,
  unit = "count",
}: {
  theme: ChartTheme;
  categories: string[];
  series: LineSeries[];
  unit?: MetricUnit;
}): EChartsOption {
  return {
    animationDuration: 500,
    grid: { left: 4, right: 20, top: series.length > 1 ? 40 : 16, bottom: 4, containLabel: true },
    tooltip: { ...tooltip(t, unit), axisPointer: { type: "line", lineStyle: { color: t.axis } } },
    legend: legend(t, series.length > 1),
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: categories,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: t.axis } },
      axisLabel: { ...axisLabel(t), interval: 0, rotate: categories.length > 8 ? 40 : 0, width: 90, overflow: "truncate" },
    },
    yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { ...axisLabel(t), formatter: compactAxis(unit) } },
    series: series.map((s, i) => ({
      type: "line",
      name: s.name,
      data: s.data.map((v) => (v == null ? "-" : v)),
      symbol: "circle",
      symbolSize: 7,
      lineStyle: { width: 2, cap: "round", join: "round" },
      itemStyle: { color: s.color ?? t.series[i % t.series.length], borderColor: t.surface, borderWidth: 2 },
      emphasis: { focus: "series" },
    })),
  };
}

/** Ordered red → green ramp for availability bands (worst first). */
export const BAND_COLORS: Record<string, string> = {
  "0%": "#7a1d1d",
  "0–30%": "#c0392b",
  "30–50%": "#e0583a",
  "50–75%": "#ec835a",
  "75–85%": "#f2a65a",
  "85–90%": "#f6c445",
  "90–95%": "#a8cf5f",
  "95–98%": "#5cb85c",
  ">98%": "#0c8a0c",
};

/** Stacked columns of availability bands per period (day or week). */
export function bandStackOption({
  theme: t,
  periods,
  bands,
  values,
  unitLabel,
}: {
  theme: ChartTheme;
  periods: string[];
  bands: string[];
  /** values[band][periodIndex] */
  values: Record<string, number[]>;
  unitLabel: string;
}): EChartsOption {
  return {
    animationDuration: 500,
    grid: { left: 4, right: 12, top: 52, bottom: 4, containLabel: true },
    tooltip: {
      ...tooltip(t, "count"),
      formatter: (raw: unknown) => {
        const params = (Array.isArray(raw) ? raw : [raw]) as AxisParam[];
        if (!params.length) return "";
        const total = params.reduce((s, p) => s + (Number(p.value) || 0), 0);
        const rows = [...params]
          .reverse()
          .map((p) => `<div style="display:flex;justify-content:space-between;gap:16px;align-items:center"><span>${p.marker}${escapeHtml(p.seriesName)}</span><b style="font-variant-numeric:tabular-nums">${formatCount(Number(p.value) || 0)}</b></div>`)
          .join("");
        return `<div style="font-weight:600;margin-bottom:4px">${escapeHtml(params[0].axisValue)} · ${formatCount(total)} ${escapeHtml(unitLabel)}</div>${rows}`;
      },
    },
    legend: { ...legend(t, true), itemGap: 10, textStyle: { color: t.muted, fontSize: 11, fontFamily: t.font } },
    xAxis: { type: "category", data: periods, axisTick: { show: false }, axisLine: { lineStyle: { color: t.axis } }, axisLabel: axisLabel(t) },
    yAxis: { type: "value", splitLine: { lineStyle: { color: t.grid } }, axisLabel: { ...axisLabel(t), formatter: compactAxis("count") } },
    series: bands.map((b, i) => ({
      type: "bar",
      name: b,
      stack: "bands",
      barMaxWidth: 46,
      data: values[b] ?? [],
      itemStyle: { color: BAND_COLORS[b] ?? t.series[i % 8], borderColor: t.surface, borderWidth: 1, borderRadius: i === bands.length - 1 ? [4, 4, 0, 0] : 0 },
      emphasis: { focus: "series" },
    })),
  };
}

/** Single-measure trend: smooth line, value on every point, soft gradient area. */
export function trendLineOption({
  theme: t,
  categories,
  values,
  name,
  unit,
  color,
}: {
  theme: ChartTheme;
  categories: string[];
  values: (number | null)[];
  name: string;
  unit: MetricUnit;
  color?: string;
}): EChartsOption {
  const c = color ?? t.series[0];
  const nums = values.filter((v): v is number => v != null);
  const lo = nums.length ? Math.min(...nums) : 0;
  return {
    animationDuration: 600,
    grid: { left: 8, right: 28, top: 36, bottom: 8, containLabel: true },
    tooltip: { ...tooltip(t, unit), axisPointer: { type: "line", lineStyle: { color: t.axis } } },
    xAxis: {
      type: "category",
      data: categories,
      // Pad the ends so the first/last point labels clear the y-axis ticks.
      boundaryGap: true,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: t.axis } },
      axisLabel: { ...axisLabel(t), fontSize: 12, hideOverlap: true },
    },
    yAxis: {
      type: "value",
      // Counts start at 0 (honest scale); percentages zoom to the data with a 100% ceiling.
      min: unit === "percent" ? Math.max(0, Math.floor((lo - 5) / 5) * 5) : 0,
      max: unit === "percent" ? 100 : undefined,
      // Counts get ~20% headroom on top so point labels never touch the top tick.
      boundaryGap: unit === "percent" ? undefined : [0, "20%"],
      // Counts are whole GPs / blocks: never draw fractional ticks.
      minInterval: unit === "percent" ? undefined : 1,
      splitLine: { lineStyle: { color: t.grid } },
      axisLabel: { ...axisLabel(t), formatter: compactAxis(unit) },
    },
    series: [
      {
        type: "line",
        name,
        data: values.map((v) => (v == null ? "-" : v)),
        smooth: 0.35,
        connectNulls: false,
        symbol: "circle",
        symbolSize: 9,
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
          formatter: (p: { value: unknown }) => (p.value == null || p.value === "-" ? "" : formatValue(Number(p.value), unit)),
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
        emphasis: { focus: "series", scale: 1.3 },
      },
    ],
  };
}
