"use client";

import { useMemo, useState } from "react";
import { barOption } from "@/components/charts/builders";
import { ChartCard } from "@/components/charts/chart-card";
import { EChart } from "@/components/charts/echart";
import { useChartTheme } from "@/components/charts/use-chart-theme";
import { ErrorState, TableSkeleton } from "@/components/feedback/states";
import { Segmented } from "@/components/ui/controls";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { api, type AmcPlanCell, type AmcPlanPeriod, type AmcPlanTable, type AmcPlanTimeline } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate } from "@/lib/utils/format";
import { FlipButton } from "@/features/circle-insights/circle-charts";
import { AreaManagerTable } from "./amc-area-managers";
import { BODY_ROW, HEAD_ROW, PctValue, RowHead, TOTAL_ROW, TableCard, Td, Th } from "./table-ui";

const dash = (v: number | null | undefined) => (v == null ? "—" : formatCount(v));
const shortDate = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "UTC" });

/** The payload narrowed to one state (state filter): that state is the only row and the table total. */
function scoped(r: AmcPlanTimeline, circle: string | undefined): AmcPlanTimeline {
  const one = (t: AmcPlanTable) => {
    const row = t.rows.find((x) => x.id === circle);
    return row ? { rows: [], total: row } : t;
  };
  if (!circle || !r.monthly.rows.some((x) => x.id === circle)) return r;
  const name = r.monthly.rows.find((x) => x.id === circle)!.name;
  const hasPlan = r.monthly.rows.find((x) => x.id === circle)!.cells.some((c) => c.target > 0 || (c.achieved ?? 0) > 0);
  return {
    ...r,
    monthly: { ...r.monthly, ...one(r.monthly) },
    weekly: { ...r.weekly, ...one(r.weekly) },
    warnings: [...r.warnings.filter((w) => !w.startsWith("No GP-wise plan in the file for")), ...(r.hasPlan && !hasPlan ? [`No GP-wise plan in the file for ${name} – counted as 0.`] : [])],
  };
}

/** Where a month target comes from: Excel = Planned Date count; Plan = targets file; Mixed = Overall of both. */
function SourceTag({ source }: { source: AmcPlanCell["targetSource"] }) {
  const label = source === "excel" ? "Excel" : source === "plan" ? "Plan" : "Mixed";
  return (
    <span
      className={cn(
        "inline-block rounded px-1 align-middle text-[10px] font-semibold uppercase tracking-wide",
        source === "excel" ? "bg-good-soft text-good-text" : source === "plan" ? "bg-warning-soft text-warning-text" : "bg-muted text-muted-foreground",
      )}
    >
      {label}
    </span>
  );
}

/**
 * Monthly / Weekly Plan vs Execution from the GP-wise plan of the master data file: target = GPs whose Planned Date
 * falls in the month / week, achieved = GPs whose Ach Date falls in it (up to the data date). Counts only.
 */
export function AmcPlanTimelineView({ view }: { view: "monthly" | "weekly" }) {
  const { period, filters } = useFilters();
  const q = useApiQuery(period ? `amc-plan-timeline:${period.weekId}` : null, () => api.getAmcPlanTimeline(period!.weekId));
  const r = q.data && scoped(q.data, filters.circle);
  // The table first; the button on its right flips the card to the graph (and back).
  const [showGraph, setShowGraph] = useState(false);
  if (q.error)
    return (
      <Card>
        <ErrorState error={q.error} onRetry={q.reload} />
      </Card>
    );
  const unit = view === "monthly" ? "Month" : "Week";
  const periods = r ? (view === "monthly" ? r.monthly.months : r.weekly.weeks) : [];
  const table = r ? (view === "monthly" ? r.monthly : r.weekly) : undefined;
  const monthly = view === "monthly";
  return (
    <div className="space-y-5">
      {/* one chip: up to which date achieved is counted (the table descriptions say what target / achieved are) */}
      {r && (
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="rounded-full bg-primary-soft px-2.5 py-1 font-medium text-primary">Latest data {formatDate(monthly ? r.monthAsOf : r.asOf)}</span>
        </div>
      )}
      {r && r.warnings.length > 0 && (
        <div role="status" className="space-y-1 rounded-lg border border-warning/50 bg-warning-soft px-4 py-3 text-sm text-warning-text">
          {r.warnings.map((w) => (
            <p key={w}>⚠ {w}</p>
          ))}
        </div>
      )}
      <section aria-label="By state">
        {showGraph && <PlanChart r={r} view={view} loading={!r} toggle={<FlipButton showGraph onToggle={() => setShowGraph(false)} />} />}
        {showGraph ? null : r && table ? (
          monthly ? (
            <MonthlyPlanTable periods={periods} table={table} asOf={r.monthAsOf} toggle={<FlipButton showGraph={false} onToggle={() => setShowGraph(true)} />} />
          ) : (
            <PlanTable unit={unit} periods={periods} table={table} weekly toggle={<FlipButton showGraph={false} onToggle={() => setShowGraph(true)} />} />
          )
        ) : (
          <Card className="p-4">
            <TableSkeleton rows={5} />
          </Card>
        )}
      </section>
      {/* one state selected: the same figures per area manager of that state (current month / selected week) */}
      {filters.circle && r?.monthly.total.id === filters.circle && (
        <section aria-label="By area manager">
          <AreaManagerTable view={view} circleId={filters.circle} />
        </section>
      )}
    </div>
  );
}

function PlanChart({ r, view, loading, toggle }: { r: AmcPlanTimeline | undefined; view: "monthly" | "weekly"; loading: boolean; toggle?: React.ReactNode }) {
  const t = useChartTheme();
  const [scope, setScope] = useState("all");
  const table = r ? (view === "monthly" ? r.monthly : r.weekly) : undefined;
  const periods = useMemo(() => (r ? (view === "monthly" ? r.monthly.months : r.weekly.weeks) : []), [r, view]);
  const row = table ? (scope === "all" ? table.total : (table.rows.find((x) => x.id === scope) ?? table.total)) : undefined;
  const option = useMemo(
    () =>
      barOption({
        theme: t,
        unit: "count",
        labels: true,
        barMaxWidth: 30,
        categories: periods.map((p) => (view === "weekly" ? `${p.label} (${shortDate(p.start)})` : p.label)),
        series: [
          { name: "Target (Planned Date)", data: row?.cells.map((c) => c.target) ?? [], color: t.series[0] },
          { name: "Achieved (Ach Date)", data: row?.cells.map((c) => c.achieved) ?? [], color: t.good },
        ],
      }),
    [periods, row, t, view],
  );
  return (
    <ChartCard
      title={view === "monthly" ? "Month-wise target vs achieved" : "Week-wise target vs achieved"}
      description={view === "monthly" ? "GPs planned (Planned Date) vs achieved (Ach Date) per month" : "GPs planned vs achieved per Fri–Thu week"}
      period={r ? `as of ${formatDate(view === "monthly" ? r.monthAsOf : r.asOf)}` : undefined}
      info="Periods not started yet have no achieved bar."
      loading={loading}
      empty={!loading && !r?.hasPlan}
      emptyMessage="The active file has no GP-wise AMC plan."
      height={260}
      actions={
        <>
          {table && table.rows.length > 0 && (
            <Segmented<string> ariaLabel="State" value={scope} onChange={setScope} options={[{ value: "all", label: "All" }, ...table.rows.map((x) => ({ value: x.id, label: x.name }))]} />
          )}
          {toggle}
        </>
      }
    >
      <EChart option={option} height={260} ariaLabel={`${view === "monthly" ? "Monthly" : "Weekly"} AMC conversion target vs achieved`} />
    </ChartCard>
  );
}

function PlanTable({ unit, periods, table, weekly, toggle }: { unit: string; periods: AmcPlanPeriod[]; table: AmcPlanTable; weekly: boolean; toggle?: React.ReactNode }) {
  // Weekly: no % column, and a week that has not started shows only its target (achieved appears once its data arrives).
  const cols = (p: AmcPlanPeriod) => (p.status === "not started" ? ["t"] : weekly ? ["t", "a"] : ["t", "a", "p"]);
  const cells = (c: AmcPlanCell, p: AmcPlanPeriod) =>
    cols(p).map((k, j) =>
      k === "t" ? (
        <Td key={`${p.id}-t`} group={j === 0} current={p.current} className={cn(weekly && "px-2")}>
          <span className="inline-flex items-center justify-end gap-1">
            {formatCount(c.target)}
            {/* monthly: only the number for file targets; targets-file months keep their PLAN tag */}
            {!weekly && c.target > 0 && c.targetSource !== "excel" && <SourceTag source={c.targetSource} />}
          </span>
          {weekly && p.status === "in progress" && c.dueTarget != null && <span className="block text-[11px] font-normal text-muted-foreground">{formatCount(c.dueTarget)} due</span>}
        </Td>
      ) : k === "a" ? (
        <Td key={`${p.id}-a`} current={p.current} className={cn("font-semibold", weekly && "px-2")}>
          {dash(c.achieved)}
        </Td>
      ) : (
        <Td key={`${p.id}-p`} current={p.current}>
          <PctValue pct={c.achievedPct} started={p.status !== "not started"} />
        </Td>
      ),
    );
  const label = (k: string) => (k === "t" ? "Target" : k === "a" ? "Achieved" : "%");
  return (
    <TableCard
      title={`${unit}-wise target vs achieved – by state`}
      description={weekly ? "Target = Planned Date in the week · Achieved = Ach Date · “due” = target GPs whose Planned Date has passed" : "Target = Planned Date in the month · Achieved = Ach Date"}
      actions={toggle}
    >
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className={cn("w-full text-[13px]", !weekly && (periods.length > 3 ? "min-w-[900px]" : "min-w-[560px]"))}>
          <caption className="sr-only">{unit}-wise AMC conversion target vs achieved by state</caption>
          <thead>
            <tr className="bg-muted">
              <Th first rowSpan={2} className="border-b border-border">
                State
              </Th>
              {periods.map((p) => (
                <Th key={p.id} colSpan={cols(p).length} center group current={p.current} className={cn(weekly && "whitespace-normal px-2 leading-tight")}>
                  {p.label}
                  {weekly && (
                    <span className="block whitespace-nowrap text-[10px] font-normal normal-case tracking-normal text-subtle-foreground">
                      {shortDate(p.start)} – {shortDate(p.end)}
                    </span>
                  )}
                  <span className="block text-[10px] font-normal normal-case tracking-normal text-subtle-foreground">
                    {p.status}
                    {p.current ? " · current" : ""}
                  </span>
                </Th>
              ))}
            </tr>
            <tr className={HEAD_ROW}>
              {periods.flatMap((p) =>
                cols(p).map((k, j) => (
                  <Th key={`${p.id}${k}`} group={j === 0} current={p.current} className={cn(weekly && "px-2")}>
                    {label(k)}
                  </Th>
                )),
              )}
            </tr>
          </thead>
          <tbody className="tabular">
            {table.rows.map((x) => (
              <tr key={x.id} className={BODY_ROW}>
                <RowHead>{x.name}</RowHead>
                {x.cells.flatMap((c, i) => cells(c, periods[i]))}
              </tr>
            ))}
          </tbody>
          <tfoot className="tabular">
            <tr className={TOTAL_ROW}>
              <RowHead total>{table.total.name === "Overall" ? "Total" : table.total.name}</RowHead>
              {table.total.cells.flatMap((c, i) => cells(c, periods[i]))}
            </tr>
          </tfoot>
        </table>
      </div>
    </TableCard>
  );
}

/* ------------------------------------------------------------------ monthly: started months in full, upcoming months grouped */

const greenPct = (v: number | null | undefined) => (v == null ? <span className="text-muted-foreground">—</span> : <span className="font-medium text-good-text">{v.toFixed(1)}%</span>);

/**
 * Month-wise target vs achieved by state. A month that has started (data for it exists) gets its own Target /
 * Achieved / Achieved % columns; the months that have not started yet share ONE "Upcoming months – target" group
 * (one column per month, target only). When a month starts, it moves out of the group by itself.
 */
function MonthlyPlanTable({ periods, table, asOf, toggle }: { periods: AmcPlanPeriod[]; table: AmcPlanTable; asOf: string; toggle?: React.ReactNode }) {
  const idx = periods.map((p, i) => ({ p, i }));
  const started = idx.filter(({ p }) => p.status !== "not started");
  const upcoming = idx.filter(({ p }) => p.status === "not started");
  const fromPlan = upcoming.some(({ i }) => table.total.cells[i]?.targetSource !== "excel");

  const row = (cells: AmcPlanCell[]) => [
    ...started.flatMap(({ p, i }) => {
      const c = cells[i];
      return [
        <Td key={`${p.id}-t`} group current={p.current} className="font-semibold">
          {formatCount(c.target)}
        </Td>,
        <Td key={`${p.id}-a`} current={p.current} className="font-semibold text-good-text">
          {dash(c.achieved)}
        </Td>,
        <Td key={`${p.id}-p`} current={p.current}>
          {greenPct(c.achievedPct)}
        </Td>,
      ];
    }),
    ...upcoming.map(({ p, i }, j) => (
      <Td key={`${p.id}-t`} group={j === 0}>
        {formatCount(cells[i].target)}
      </Td>
    )),
  ];

  return (
    <TableCard title="Month-wise target vs achieved – by state" description={`Target = Planned Date in the month · Achieved = Ach Date (up to ${formatDate(asOf)})`} actions={toggle}>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-[13px]">
          <caption className="sr-only">Month-wise AMC conversion target vs achieved by state</caption>
          <thead>
            <tr className="bg-muted">
              <Th first rowSpan={2} className="border-b border-border">
                State
              </Th>
              {started.map(({ p }) => (
                <Th key={p.id} colSpan={3} center group current={p.current}>
                  {p.label}
                  <span className="block text-[10px] font-normal normal-case tracking-normal text-subtle-foreground">{p.current ? "current month" : p.status}</span>
                </Th>
              ))}
              {upcoming.length > 0 && (
                <Th colSpan={upcoming.length} center group>
                  Upcoming months – target
                  <span className="block text-[10px] font-normal normal-case tracking-normal text-subtle-foreground">not started yet</span>
                </Th>
              )}
            </tr>
            <tr className={HEAD_ROW}>
              {started.flatMap(({ p }) => [
                <Th key={`${p.id}t`} group current={p.current}>
                  Target
                </Th>,
                <Th key={`${p.id}a`} current={p.current}>
                  Achieved
                </Th>,
                <Th key={`${p.id}p`} current={p.current}>
                  Achieved %
                </Th>,
              ])}
              {upcoming.map(({ p }, j) => (
                <Th key={`${p.id}u`} group={j === 0}>
                  {p.label}
                </Th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {table.rows.map((x) => (
              <tr key={x.id} className={BODY_ROW}>
                <RowHead>{x.name}</RowHead>
                {row(x.cells)}
              </tr>
            ))}
          </tbody>
          <tfoot className="tabular">
            <tr className={TOTAL_ROW}>
              <RowHead total>{table.total.name === "Overall" ? "Total" : table.total.name}</RowHead>
              {row(table.total.cells)}
            </tr>
          </tfoot>
        </table>
      </div>
      {/* only when an upcoming target is not from the file's Planned Dates yet */}
      {fromPlan && <p className="mt-2 px-1 text-xs text-muted-foreground">Upcoming targets from the management plan until their Planned Dates arrive in the data.</p>}
    </TableCard>
  );
}
