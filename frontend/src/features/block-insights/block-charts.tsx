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
