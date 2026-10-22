"use client";

import { useMemo, useState } from "react";
import { barOption } from "@/components/charts/builders";
import { ChartCard } from "@/components/charts/chart-card";
import { EChart } from "@/components/charts/echart";
import { useChartTheme } from "@/components/charts/use-chart-theme";
import { SummaryTable, type SummaryColumn } from "@/components/tables/summary-table";
import { Segmented } from "@/components/ui/controls";
import type { KpiListKind, OverviewResponse } from "@/lib/api";
import type { KpiListGroup } from "@/lib/kpi-lists";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { formatCount, formatDate } from "@/lib/utils/format";

type Row = NonNullable<OverviewResponse["stateDetails"]>[number];

interface Props {
  data: OverviewResponse | undefined;
  loading: boolean;
  onOpenCircle: (id: string) => void;
  /** Table row click: the state's own page – a group of lists (GP details, network health, HOTO, converted / closed), opened on `kind` */
  onOpenState?: (id: string, group: KpiListGroup, kind?: KpiListKind) => void;
}

const sum = (rows: Row[], pick: (r: Row) => number | null | undefined) => rows.reduce((s, r) => s + (pick(r) ?? 0), 0);
const pct = (a: number, b: number) => (b ? `${((a / b) * 100).toFixed(1)}%` : "NA");

function Completion({ done, total }: { done: number; total: number }) {
  const w = total ? (done / total) * 100 : 0;
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-muted sm:block" aria-hidden>
        <span className="block h-full rounded-full bg-good" style={{ width: `${w}%` }} />
      </span>
      {pct(done, total)}
    </span>
  );
}

/* ------------------------------------------------------------------ 1. Network health */

export function NetworkHealth({ data, loading, onOpenCircle, onOpenState }: Props) {
  const t = useChartTheme();
  const rows = useMemo(() => data?.stateDetails ?? [], [data]);
  const option = useMemo(
    () =>
      barOption({
        theme: t,
        unit: "count",
        labels: true,
        compactLabels: true,
        legendRows: 2,
        barMaxWidth: 34,
        categories: rows.map((r) => r.name),
        series: [
          { name: `GPs above ${THRESHOLDS.healthy}% (MTD)`, data: rows.map((r) => r.gpsAbove98), color: t.good },
          { name: "GPs at 0% (MTD)", data: rows.map((r) => r.gpsAtZero), color: t.critical },
          { name: `Penalty-prone blocks <${THRESHOLDS.penalty}%`, data: rows.map((r) => r.penaltyBlocks), color: t.serious },
          { name: "One-time UP GPs (Sept-26)", data: rows.map((r) => r.oneTimeUp), color: t.series[0] },
        ],
      }),
    [rows, t],
  );
  // Same figures as the bars, one row per state; a row opens that state's lists (GP names behind each number).
  const healthCols: SummaryColumn<Row>[] = [
    { key: "name", header: "State", render: (r) => r.name },
    { key: "amc", header: "AMC GPs", numeric: true, render: (r) => formatCount(r.amcGps) },
    { key: "a98", header: `GPs >${THRESHOLDS.healthy}%`, numeric: true, render: (r) => formatCount(r.gpsAbove98) },
    { key: "zero", header: "GPs at 0%", numeric: true, render: (r) => formatCount(r.gpsAtZero) },
    { key: "pen", header: `Blocks <${THRESHOLDS.penalty}%`, numeric: true, render: (r) => formatCount(r.penaltyBlocks) },
    { key: "otu", header: "One-time UP", numeric: true, render: (r) => formatCount(r.oneTimeUp) },
  ];
  return (
    <ChartCard
      title="State-wise Network Health"
      description={`GPs above ${THRESHOLDS.healthy}% and at 0% (month to date), penalty-prone blocks and one-time UP GPs · select a row to see the GPs behind each number`}
      period={data?.asOf ? `MTD up to ${formatDate(data.asOf)}` : undefined}
      info="MTD = mean of daily availability from the 1st of the month (or the GP's AMC date). NA GPs are excluded from averages and never counted as 0%. Penalty-prone blocks are counted in blocks, the other bars in GPs. One-time UP = GPs with September availability above 0%."
      loading={loading}
      empty={!loading && rows.length === 0}
      height={340}
    >
      <EChart option={option} height={340} ariaLabel="Network health by state" />
      <div className="mt-4">
        <SummaryTable
          columns={healthCols}
          rows={rows}
          total={{
            name: "Total",
            amc: formatCount(sum(rows, (r) => r.amcGps)),
            a98: formatCount(sum(rows, (r) => r.gpsAbove98)),
            zero: formatCount(sum(rows, (r) => r.gpsAtZero)),
            pen: formatCount(sum(rows, (r) => r.penaltyBlocks)),
            otu: formatCount(sum(rows, (r) => r.oneTimeUp)),
          }}
          rowKey={(r) => r.id}
          onRowClick={(r) => (onOpenState ? onOpenState(r.id, "health") : onOpenCircle(r.id))}
          rowLabel={(r) => `Open the network-health lists of ${r.name}`}
          caption="State-wise network health"
        />
      </div>
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ 2. HOTO blocks / GPs */

type HotoView = "blocks" | "gps";

export function HotoProgress({ data, loading, onOpenCircle, onOpenState }: Props) {
  const t = useChartTheme();
  const [view, setView] = useState<HotoView>("gps");
  const rows = useMemo(() => data?.stateDetails ?? [], [data]);
  const option = useMemo(() => {
    const done = (r: Row) => (view === "blocks" ? r.hotoDoneBlocks : r.hotoDoneGps);
    const pending = (r: Row) => (view === "blocks" ? r.hotoPendingBlocks : r.hotoPendingGps);
    return barOption({
      theme: t,
      unit: "count",
      horizontal: true,
      barMaxWidth: 26,
      categories: rows.map((r) => r.name),
      series: [
        { name: "HOTO done", data: rows.map(done), stack: "h", color: t.good },
        { name: "Pending", data: rows.map(pending), stack: "h", color: t.warning },
      ],
    });
  }, [rows, t, view]);
  const done = (r: Row) => (view === "blocks" ? r.hotoDoneBlocks : r.hotoDoneGps);
  const pending = (r: Row) => (view === "blocks" ? r.hotoPendingBlocks : r.hotoPendingGps);
  const unit = view === "blocks" ? "Blocks" : "GPs";
  const cols: SummaryColumn<Row>[] = [
    { key: "name", header: "State", render: (r) => r.name },
    { key: "scope", header: view === "blocks" ? "Total blocks" : "Revised existing", numeric: true, render: (r) => formatCount(done(r) + pending(r)) },
    { key: "done", header: "Done", numeric: true, render: (r) => formatCount(done(r)) },
    { key: "pending", header: "Pending", numeric: true, render: (r) => formatCount(pending(r)) },
    { key: "pct", header: "Completion", numeric: true, render: (r) => <Completion done={done(r)} total={done(r) + pending(r)} /> },
  ];
  const D = sum(rows, done);
  const Pn = sum(rows, pending);
  return (
    <ChartCard
      title={`State-wise HOTO Done — ${unit}`}
      description={view === "blocks" ? "Blocks with at least one HOTO-done GP" : "Revised existing GPs handed over vs pending"}
      period={data?.asOf ? `as of ${formatDate(data.asOf)}` : undefined}
      loading={loading}
      empty={!loading && rows.length === 0}
      height={220}
      actions={
        <Segmented<HotoView>
          ariaLabel="Show HOTO for"
          value={view}
          onChange={setView}
          options={[
            { value: "gps", label: "GPs" },
            { value: "blocks", label: "Blocks" },
          ]}
        />
      }
    >
      <EChart option={option} height={220} ariaLabel={`HOTO done ${unit} by state`} />
      <div className="mt-4">
        <SummaryTable
          columns={cols}
          rows={rows}
          rowKey={(r) => r.id}
          total={{ name: "Total", scope: formatCount(D + Pn), done: formatCount(D), pending: formatCount(Pn), pct: <Completion done={D} total={D + Pn} /> }}
          caption={`HOTO ${unit} by state`}
          onRowClick={(r) => (onOpenState ? onOpenState(r.id, "hoto", view === "blocks" ? "hoto-blocks" : "hoto-gps") : onOpenCircle(r.id))}
          rowLabel={(r) => `Open HOTO details for ${r.name}`}
        />
      </div>
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ 3. Converted to NP / closed */

const convertedCols: SummaryColumn<Row>[] = [
  { key: "name", header: "State", render: (r) => r.name },
  { key: "np", header: "Converted to NP", numeric: true, render: (r) => formatCount(r.convertedNp) },
  { key: "closed", header: "Permanently closed", numeric: true, render: (r) => formatCount(r.permanentlyClosed) },
  { key: "deducted", header: "Deducted (portal entry)", numeric: true, render: (r) => formatCount(r.deductedGps) },
  { key: "total", header: "Total", numeric: true, render: (r) => <span className="font-semibold">{formatCount(r.convertedOrClosed)}</span> },
];

export function ConvertedGps({ data, loading, onOpenCircle, onOpenState }: Props) {
  const t = useChartTheme();
  const rows = useMemo(() => data?.stateDetails ?? [], [data]);
  const option = useMemo(
    () =>
      barOption({
        theme: t,
        unit: "count",
        labels: true,
        legendRows: 2,
        barMaxWidth: 34,
        categories: rows.map((r) => r.name),
        series: [
          { name: "Converted to Nagar Palika", data: rows.map((r) => r.convertedNp), color: t.series[3] },
          { name: "Permanently closed", data: rows.map((r) => r.permanentlyClosed), color: t.series[7] },
          { name: "Deducted during portal entry", data: rows.map((r) => r.deductedGps), color: t.series[6] },
        ],
      }),
    [rows, t],
  );
  return (
    <ChartCard
      title="GPs Converted to NP / Closed"
      description="Existing GPs removed from scope, by reason"
      info="From the “Converted to NP & Closed” column. The source records no date for these changes, so they apply to every reporting week."
      loading={loading}
      empty={!loading && rows.length === 0}
      height={220}
    >
      <EChart option={option} height={220} ariaLabel="GPs converted or closed by state" />
      <div className="mt-4">
        <SummaryTable
          columns={convertedCols}
          rows={rows}
          rowKey={(r) => r.id}
          total={{
            name: "Total",
            np: formatCount(sum(rows, (r) => r.convertedNp)),
            closed: formatCount(sum(rows, (r) => r.permanentlyClosed)),
            deducted: formatCount(sum(rows, (r) => r.deductedGps)),
            total: formatCount(sum(rows, (r) => r.convertedOrClosed)),
          }}
          caption="GPs converted to NP / closed by state"
          onRowClick={(r) => (onOpenState ? onOpenState(r.id, "converted", "removed-gps") : onOpenCircle(r.id))}
          rowLabel={(r) => `Open converted / closed GPs of ${r.name}`}
        />
      </div>
    </ChartCard>
  );
}
