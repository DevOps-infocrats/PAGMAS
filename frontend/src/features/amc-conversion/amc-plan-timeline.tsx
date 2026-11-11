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
import { BODY_ROW, GRID_TABLE, GRID_WRAP, HEAD_ROW, RowHead, TOTAL_ROW, TableCard, Td, Th } from "./table-ui";

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

/** Management plan figure of a month (targets file) – reference only, never the target. */
function PlanRef({ v }: { v: number }) {
  return (
    <span className="block text-[0.625rem] font-normal text-muted-foreground" title="Management plan (targets file) – for reference only, not counted as the target">
      plan {formatCount(v)}
    </span>
  );
}

/** Where a month target comes from: Excel = Planned Date count; Plan = targets file; Mixed = Overall of both. */
function SourceTag({ source }: { source: AmcPlanCell["targetSource"] }) {
  const label = source === "excel" ? "Excel" : source === "plan" ? "Plan" : "Mixed";
  return (
    <span
      className={cn(
        "inline-block rounded px-1 align-middle text-[0.625rem] font-semibold uppercase tracking-wide",
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
    <div className="space-y-3">
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
        <section aria-label="By area manager" className="pt-2">
          <AreaManagerTable view={view} circleId={filters.circle} />
        </section>
      )}
    </div>
  );
}

/**
 * Up to which date achieved is counted – shown in the page's title bar (Monthly: latest data of the month; Weekly: of the
 * selected week). Same request as the page (shared by key), so nothing is fetched twice.
 */
export function AmcTimelineDateChip({ view }: { view: "monthly" | "weekly" }) {
  const { period } = useFilters();
  const q = useApiQuery(period ? `amc-plan-timeline:${period.weekId}` : null, () => api.getAmcPlanTimeline(period!.weekId));
  const r = q.data ?? q.staleData;
  if (!r) return null;
  return <span className="inline-flex rounded-full bg-primary-soft px-2.5 py-0.5 text-xs font-medium text-primary">Latest data {formatDate(view === "monthly" ? r.monthAsOf : r.asOf)}</span>;
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
          { name: "GP Ready (Ach Date)", data: row?.cells.map((c) => c.ready) ?? [], color: t.series[1] },
          { name: "GP Achieved (AMC Date)", data: row?.cells.map((c) => c.converted) ?? [], color: t.good },
        ],
      }),
    [periods, row, t, view],
  );
  return (
    <ChartCard
      title={view === "monthly" ? "Month-wise target vs achieved" : "Week-wise target vs achieved"}
      description={view === "monthly" ? "GPs planned (Planned Date), ready (Ach Date) and achieved (AMC Date) per month" : "GPs planned, ready and achieved per week (as in the master data sheet)"}
      period={r ? `as of ${formatDate(view === "monthly" ? r.monthAsOf : r.asOf)}` : undefined}
      info="Periods not started yet have no ready / achieved bar."
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

/* ------------------------------------------------------------------ Target / GP Ready / GP Achieved / Gap tables */

/** The four columns of a started period. Short headers keep many periods on screen without scrolling. */
const MEASURES = [
  { key: "t", head: "Target", title: "Target – GPs whose Planned Date falls in the period" },
  { key: "r", head: "Ready", title: "GP Ready – GPs whose Ach Date falls in the period" },
  { key: "a", head: "Ach.", title: "GP Achieved – plan GPs whose AMC Date (letter accepted) falls in the period" },
  { key: "g", head: "Gap", title: "Gap = Target − GP Achieved" },
] as const;

/** Light green tint of the month / week the user clicked (header, column headers and every cell of the group). */
const PICKED = "bg-good-soft transition-colors duration-200";

/**
 * One highlighted column group at a time: clicking a month / week header selects it, clicking it again clears it.
 * Keyed by the period id (2026-10, W-44 …), so it works for every period and survives data refreshes.
 */
function usePickedPeriod() {
  const [picked, setPicked] = useState<string | null>(null);
  return { picked, toggle: (id: string) => setPicked((cur) => (cur === id ? null : id)) };
}

/** Clickable group header content (button for keyboard use; the whole cell is the click target). */
function PickButton({ id, picked, onPick, label, children }: { id: string; picked: boolean; onPick: (id: string) => void; label: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={() => onPick(id)}
      aria-pressed={picked}
      title={picked ? `Remove the highlight of ${label}` : `Highlight all columns of ${label}`}
      className="block w-full cursor-pointer rounded-sm px-1 py-0.5 text-inherit focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
    >
      {children}
    </button>
  );
}

/** Gap: still to do in red, nothing left (or more achieved than planned) in green. */
function GapValue({ v }: { v: number | null }) {
  if (v == null) return <span className="text-muted-foreground">—</span>;
  return <span className={cn("font-semibold", v > 0 ? "text-critical-text" : "text-good-text")}>{v < 0 ? `+${formatCount(-v)}` : formatCount(v)}</span>;
}

function measureCells(c: AmcPlanCell, p: AmcPlanPeriod, compact: boolean, sourceTag: boolean, picked: boolean) {
  const pad = compact ? "px-1 text-[0.75rem]" : "px-2.5";
  return MEASURES.map((m, j) => (
    <Td key={`${p.id}-${m.key}`} group={j === 0} current={p.current} className={cn(pad, m.key === "t" && "font-semibold", m.key === "a" && "font-semibold text-good-text", picked && PICKED)}>
      {m.key === "t" ? (
        <span className="inline-flex items-center justify-end gap-1">
          {formatCount(c.target)}
          {sourceTag && c.target > 0 && c.targetSource !== "excel" && <SourceTag source={c.targetSource} />}
          {sourceTag && c.planTarget != null && <PlanRef v={c.planTarget} />}
        </span>
      ) : m.key === "r" ? (
        dash(c.ready)
      ) : m.key === "a" ? (
        dash(c.converted)
      ) : (
        <GapValue v={c.gap} />
      )}
    </Td>
  ));
}

const LEGEND = "Target = Planned Date · Ready = Ach Date · Ach. = GP Achieved (AMC Date, letter accepted) · Gap = Target − Achieved";
const PICK_HINT = (unit: "month" | "week") => `Click a ${unit} heading to highlight its columns.`;
const HEAD_HOVER = "cursor-pointer hover:bg-good-soft/60";

/**
 * Week-wise table: every week that has started gets Target / Ready / Achieved / Gap; a week not started yet shows its
 * target only. Compact cells so all the weeks fit the card without horizontal scrolling. Click a week to highlight it.
 */
function PlanTable({ unit, periods, table, toggle }: { unit: string; periods: AmcPlanPeriod[]; table: AmcPlanTable; weekly: boolean; toggle?: React.ReactNode }) {
  const { picked, toggle: pick } = usePickedPeriod();
  const started = (p: AmcPlanPeriod) => p.status !== "not started";
  const row = (cells: AmcPlanCell[]) =>
    periods.flatMap((p, i) =>
      started(p)
        ? measureCells(cells[i], p, true, false, picked === p.id)
        : [
            <Td key={`${p.id}-t`} group current={p.current} className={cn("px-1 text-[0.75rem] font-semibold", picked === p.id && PICKED)}>
              {formatCount(cells[i].target)}
            </Td>,
          ],
    );
  return (
    <TableCard title={`${unit}-wise target vs achieved – by state`} description={`${LEGEND} · ${PICK_HINT("week")}`} actions={toggle}>
      <div className={GRID_WRAP}>
        <table className={cn("w-full text-[0.75rem]", GRID_TABLE)}>
          <caption className="sr-only">{unit}-wise AMC conversion target, ready, achieved and gap by state</caption>
          <thead>
            <tr className="bg-muted">
              <Th first rowSpan={2} className="border-b border-border">
                State
              </Th>
              {periods.map((p) => (
                <Th
                  key={p.id}
                  colSpan={started(p) ? MEASURES.length : 1}
                  center
                  group
                  current={p.current}
                  className={cn("whitespace-normal px-0.5 leading-tight", HEAD_HOVER, picked === p.id && PICKED)}
                  onClick={(e) => e.target === e.currentTarget && pick(p.id)}
                >
                  <PickButton id={p.id} picked={picked === p.id} onPick={pick} label={p.label}>
                    {p.label}
                    <span className="block whitespace-nowrap text-[0.625rem] font-normal normal-case tracking-normal text-subtle-foreground">
                      {shortDate(p.start)} – {shortDate(p.end)}
                      {p.status === "in progress" ? " · now" : p.status === "not started" ? " · next" : ""}
                    </span>
                  </PickButton>
                </Th>
              ))}
            </tr>
            <tr className={HEAD_ROW}>
              {periods.flatMap((p) =>
                started(p)
                  ? MEASURES.map((m, j) => (
                      <Th key={`${p.id}${m.key}`} group={j === 0} current={p.current} title={m.title} className={cn("px-1 text-[0.6875rem]", picked === p.id && PICKED)}>
                        {m.head}
                      </Th>
                    ))
                  : [
                      <Th key={`${p.id}t`} group current={p.current} className={cn("px-1 text-[0.6875rem]", picked === p.id && PICKED)}>
                        Target
                      </Th>,
                    ],
              )}
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
    </TableCard>
  );
}

/**
 * Month-wise table: a month that has started gets Target / GP Ready / GP Achieved / Gap; the months not started yet
 * share ONE "Upcoming months – target" group (target only). When a month starts, it moves out of the group by itself.
 * Click a month (an upcoming month: its column heading) to highlight its columns.
 */
function MonthlyPlanTable({ periods, table, asOf, toggle }: { periods: AmcPlanPeriod[]; table: AmcPlanTable; asOf: string; toggle?: React.ReactNode }) {
  const { picked, toggle: pick } = usePickedPeriod();
  const idx = periods.map((p, i) => ({ p, i }));
  const started = idx.filter(({ p }) => p.status !== "not started");
  const upcoming = idx.filter(({ p }) => p.status === "not started");
  const withPlan = idx.some(({ i }) => table.total.cells[i]?.planTarget != null);

  const row = (cells: AmcPlanCell[]) => [
    ...started.flatMap(({ p, i }) => measureCells(cells[i], p, false, true, picked === p.id)),
    ...upcoming.map(({ p, i }, j) => (
      <Td key={`${p.id}-t`} group={j === 0} className={cn(picked === p.id && PICKED)}>
        {formatCount(cells[i].target)}
        {cells[i].planTarget != null && <PlanRef v={cells[i].planTarget!} />}
      </Td>
    )),
  ];

  return (
    <TableCard title="Month-wise target vs achieved – by state" description={`${LEGEND} (up to ${formatDate(asOf)}) · ${PICK_HINT("month")}`} actions={toggle}>
      <div className={GRID_WRAP}>
        <table className={cn("w-full text-[0.8125rem]", GRID_TABLE)}>
          <caption className="sr-only">Month-wise AMC conversion target, ready, achieved and gap by state</caption>
          <thead>
            <tr className="bg-muted">
              <Th first rowSpan={2} className="border-b border-border">
                State
              </Th>
              {started.map(({ p }) => (
                <Th
                  key={p.id}
                  colSpan={MEASURES.length}
                  center
                  group
                  current={p.current}
                  className={cn(HEAD_HOVER, picked === p.id && PICKED)}
                  onClick={(e) => e.target === e.currentTarget && pick(p.id)}
                >
                  <PickButton id={p.id} picked={picked === p.id} onPick={pick} label={p.label}>
                    {p.label}
                    <span className="block text-[0.625rem] font-normal normal-case tracking-normal text-subtle-foreground">{p.current ? "current month" : p.status}</span>
                  </PickButton>
                </Th>
              ))}
              {upcoming.length > 0 && (
                <Th colSpan={upcoming.length} center group>
                  Upcoming months – target
                  <span className="block text-[0.625rem] font-normal normal-case tracking-normal text-subtle-foreground">not started yet</span>
                </Th>
              )}
            </tr>
            <tr className={HEAD_ROW}>
              {started.flatMap(({ p }) =>
                MEASURES.map((m, j) => (
                  <Th key={`${p.id}${m.key}`} group={j === 0} current={p.current} title={m.title} className={cn(picked === p.id && PICKED)}>
                    {m.key === "r" ? "GP Ready" : m.key === "a" ? "GP Achieved" : m.head}
                  </Th>
                )),
              )}
              {upcoming.map(({ p }, j) => (
                <Th key={`${p.id}u`} group={j === 0} className={cn(HEAD_HOVER, picked === p.id && PICKED)} onClick={(e) => e.target === e.currentTarget && pick(p.id)}>
                  <PickButton id={p.id} picked={picked === p.id} onPick={pick} label={p.label}>
                    {p.label}
                  </PickButton>
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
      {withPlan && (
        <p className="mt-2 px-1 text-xs text-muted-foreground">
          Targets are counted from the Planned Dates of the master data only. “Plan” under a target = the management plan (targets file) for reference – it is never used as the target, in the totals or in the gap.
        </p>
      )}
    </TableCard>
  );
}
