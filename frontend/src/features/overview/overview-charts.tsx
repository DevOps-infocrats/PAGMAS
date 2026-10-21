"use client";

import { useMemo, useState } from "react";
import { barOption } from "@/components/charts/builders";
import { ChartCard } from "@/components/charts/chart-card";
import { EChart } from "@/components/charts/echart";
import { useChartTheme } from "@/components/charts/use-chart-theme";
import { AvailabilityValue } from "@/components/feedback/badges";
import { SummaryTable, type SummaryColumn } from "@/components/tables/summary-table";
import { Segmented } from "@/components/ui/controls";
import type { KpiListKind, OverviewResponse } from "@/lib/api";
import type { KpiListGroup } from "@/lib/kpi-lists";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate, formatPercent } from "@/lib/utils/format";

type Row = NonNullable<OverviewResponse["stateDetails"]>[number];
type Manager = OverviewResponse["areaManagers"][number];

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

/* ------------------------------------------------------------------ 1. State-wise comparison */

export function StateComparison({ data, loading, onOpenCircle, onOpenState }: Props) {
  const t = useChartTheme();
  const rows = useMemo(() => data?.stateDetails ?? [], [data]);
  const option = useMemo(
    () =>
      barOption({
        theme: t,
        unit: "count",
        labels: true,
        compactLabels: true,
        barMaxWidth: 28,
        categories: rows.map((r) => r.name),
        series: [
          { name: "Total GPs", data: rows.map((r) => r.totalGps ?? r.existingGps), color: t.series[0] },
          { name: "Revised existing", data: rows.map((r) => r.revisedExisting), color: t.series[6] },
          { name: "HOTO done", data: rows.map((r) => r.hotoDoneGps), color: t.series[2] },
          { name: "AMC GPs", data: rows.map((r) => r.amcGps), color: t.series[1] },
        ],
      }),
    [rows, t],
  );
  const cols: SummaryColumn<Row>[] = [
    { key: "name", header: "State", render: (r) => r.name },
    { key: "blocks", header: "Blocks", numeric: true, render: (r) => formatCount(r.blocks) },
    { key: "total", header: "Total GPs", numeric: true, render: (r) => formatCount(r.totalGps) },
    { key: "existing", header: "Existing", numeric: true, render: (r) => formatCount(r.existingGps) },
    { key: "new", header: "New", numeric: true, render: (r) => formatCount(r.newGps) },
    { key: "revised", header: "Revised existing", numeric: true, render: (r) => formatCount(r.revisedExisting) },
    { key: "hoto", header: "HOTO done", numeric: true, render: (r) => formatCount(r.hotoDoneGps) },
    { key: "amc", header: "AMC GPs", numeric: true, render: (r) => formatCount(r.amcGps) },
    { key: "amcPct", header: "AMC %", numeric: true, render: (r) => formatPercent(r.amcPct) },
  ];
  const tot = {
    name: "Total",
    blocks: formatCount(sum(rows, (r) => r.blocks)),
    total: formatCount(sum(rows, (r) => r.totalGps)),
    existing: formatCount(sum(rows, (r) => r.existingGps)),
    new: formatCount(sum(rows, (r) => r.newGps)),
    revised: formatCount(sum(rows, (r) => r.revisedExisting)),
    hoto: formatCount(sum(rows, (r) => r.hotoDoneGps)),
    amc: formatCount(sum(rows, (r) => r.amcGps)),
    amcPct: pct(sum(rows, (r) => r.amcGps), sum(rows, (r) => r.revisedExisting)),
  };
  return (
    <ChartCard
      title="State-wise Comparison"
      description="GP scope, handover and AMC coverage per state · select a row to see the state's existing and new GPs"
      info="Total GPs = existing + new (Master Block). Revised existing excludes GPs converted to NP, closed or deducted. AMC % = AMC GPs ÷ revised existing."
      loading={loading}
      empty={!loading && rows.length === 0}
      height={320}
    >
      <EChart option={option} height={320} ariaLabel="GP counts by state" onClick={(p) => rows[p.dataIndex] && onOpenCircle(rows[p.dataIndex].id)} />
      <div className="mt-4">
        <SummaryTable
          columns={cols}
          rows={rows}
          total={tot}
          rowKey={(r) => r.id}
          onRowClick={(r) => (onOpenState ? onOpenState(r.id, "comparison") : onOpenCircle(r.id))}
          rowLabel={(r) => `Open the existing and new GPs of ${r.name}`}
          caption="State-wise comparison"
        />
      </div>
    </ChartCard>
  );
}

/* ------------------------------------------------------------------ 2. Network health */

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
    { key: "na", header: "Not reported (NA)", numeric: true, render: (r) => formatCount(r.naGps) },
    { key: "pen", header: `Blocks <${THRESHOLDS.penalty}%`, numeric: true, render: (r) => formatCount(r.penaltyBlocks) },
    { key: "otu", header: "One-time UP", numeric: true, render: (r) => formatCount(r.oneTimeUp) },
    { key: "avail", header: "Avg availability", numeric: true, render: (r) => <AvailabilityValue value={r.availability} /> },
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
            na: formatCount(sum(rows, (r) => r.naGps)),
            pen: formatCount(sum(rows, (r) => r.penaltyBlocks)),
            otu: formatCount(sum(rows, (r) => r.oneTimeUp)),
            avail: <AvailabilityValue value={data?.summary?.availability ?? null} />,
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

/* ------------------------------------------------------------------ 3. HOTO blocks / GPs */

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

/* ------------------------------------------------------------------ 4. Converted to NP / closed */

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

/* ------------------------------------------------------------------ 5. Area managers */

export function AreaManagerTable({ data, loading }: Props) {
  const [state, setState] = useState<string>("all");
  const circles = data?.stateDetails ?? [];
  const nameOf = (id: string) => circles.find((c) => c.id === id)?.name ?? id;
  const rows = useMemo(() => {
    const list = (data?.areaManagers ?? []).filter((m) => state === "all" || m.circleId === state);
    return [...list].sort((a, b) => {
      const ua = a.manager.label === "Unassigned" ? 1 : 0;
      const ub = b.manager.label === "Unassigned" ? 1 : 0;
      return ua - ub || (b.availability ?? -1) - (a.availability ?? -1);
    });
  }, [data, state]);
  const cols: SummaryColumn<Manager>[] = [
    {
      key: "am",
      header: "Area manager",
      render: (m) => (
        <span className={cn(m.manager.label === "Unassigned" && "italic text-muted-foreground")}>{m.manager.label === "Unassigned" ? "Not assigned in source" : m.manager.label}</span>
      ),
    },
    { key: "state", header: "State", render: (m) => nameOf(m.circleId) },
    { key: "blocks", header: "Blocks", numeric: true, render: (m) => formatCount(m.blocks ?? null) },
    { key: "gps", header: "GPs", numeric: true, render: (m) => formatCount(m.revisedExisting ?? m.gps) },
    { key: "amc", header: "AMC GPs", numeric: true, render: (m) => formatCount(m.amcGps ?? null) },
    { key: "avail", header: "Availability (MTD)", numeric: true, render: (m) => <AvailabilityValue value={m.availability} /> },
    { key: "a98", header: `>${THRESHOLDS.healthy}%`, numeric: true, render: (m) => formatCount(m.gpsAbove98) },
    { key: "zero", header: "At 0%", numeric: true, render: (m) => formatCount(m.gpsAtZero ?? null) },
    { key: "pen", header: `Blocks <${THRESHOLDS.penalty}%`, numeric: true, render: (m) => formatCount(m.penaltyBlocks) },
  ];
  const unassigned = rows.filter((m) => m.manager.label === "Unassigned").reduce((s, m) => s + m.gps, 0);
  return (
    <ChartCard
      title="Area Manager Performance — State-wise"
      description="AMC availability and penalty exposure of the GPs each area manager covers"
      period={data?.asOf ? `MTD up to ${formatDate(data.asOf)}` : undefined}
      info="Area manager = 'AM Name' column of GP Wise Data. GPs without a valid name are grouped as “Not assigned in source”."
      loading={loading}
      empty={!loading && rows.length === 0}
      actions={
        <Segmented<string>
          ariaLabel="State"
          value={state}
          onChange={setState}
          options={[{ value: "all", label: "All" }, ...circles.map((c) => ({ value: c.id, label: c.name }))]}
        />
      }
    >
      <SummaryTable columns={cols} rows={rows} rowKey={(m) => m.manager.id} caption="Area manager performance" />
      {unassigned > 0 && (
        <p className="mt-3 text-xs text-muted-foreground">
          {formatCount(unassigned)} GPs have no area manager name in the source file – fill the “AM Name” column to attribute them.
        </p>
      )}
    </ChartCard>
  );
}
