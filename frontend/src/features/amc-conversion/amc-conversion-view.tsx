"use client";

import { CalendarRange, Hourglass, Target, Wrench } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { ErrorState } from "@/components/feedback/states";
import { CircleFilter } from "@/components/filters/filter-bar";
import { Breadcrumbs } from "@/components/layout/page-header";
import { useMeta } from "@/components/providers/data-provider";
import { StatCard } from "@/components/kpi/stat-card";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { AMC_PATH, AMC_VIEWS, amcViewFrom } from "@/lib/amc-views";
import { api, type AmcConversionResponse } from "@/lib/api";
import { formatCount, formatDate, formatPercent } from "@/lib/utils/format";
import { AmcConversionCards } from "@/features/review/review-tabs";
import { AmcPlanSummaryView } from "./amc-plan-summary";
import { AmcPlanTimelineView } from "./amc-plan-timeline";
import { BODY_ROW, HEAD_ROW, RowHead, TOTAL_ROW, TableCard, Td, Th } from "./table-ui";

type R = AmcConversionResponse;

const dash = (v: number | null | undefined) => (v == null ? "—" : formatCount(v));

/**
 * AMC Conversion – Plan vs Execution, one view at a time (?view=, sidebar sub-menu):
 *  summary / monthly / weekly – GP-wise plan of the master data file (Planned Date = target, Ach Date = achieved)
 *  current – O&M projection, gap and pending scope, as in Management Review → Target & Achievement
 */
export function AmcConversionView() {
  const params = useSearchParams();
  const meta = useMeta();
  const { filters, hrefTo } = useFilters();
  const view = AMC_VIEWS.find((v) => v.id === amcViewFrom(params.get("view")))!;
  const stateName = meta?.circles.find((c) => c.id === filters.circle)?.name;
  const pageHref = (() => {
    const base = hrefTo(AMC_PATH, { circle: undefined, district: undefined, block: undefined, gp: undefined });
    return `${base}${base.includes("?") ? "&" : "?"}view=${view.id}`;
  })();
  return (
    <div className="space-y-5">
      {/* ---------------- Title bar: same in every view, like the other pages ---------------- */}
      <header className="rounded-xl border border-border bg-card shadow-sm">
        <div className="space-y-0.5 px-4 py-2.5">
          <Breadcrumbs
            items={[
              { label: "Circle Overview", href: hrefTo("/dashboard", { circle: undefined, district: undefined, block: undefined, gp: undefined }) },
              stateName ? { label: "AMC Conversion Plan vs Execution", href: pageHref } : { label: "AMC Conversion Plan vs Execution" },
              ...(stateName ? [{ label: stateName }] : []),
            ]}
          />
          <h1 className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-lg font-semibold leading-tight">
            {stateName ?? "AMC Conversion Plan vs Execution"}
            <span className="text-subtle-foreground" aria-hidden>
              ·
            </span>
            <span className="text-primary">{view.title}</span>
            <span className="text-[13px] font-normal text-muted-foreground">{stateName ? "AMC conversion plan vs execution of this state." : "All states – select a state to see only its figures."}</span>
          </h1>
        </div>
        {/* State (shared filter); the view is kept */}
        <div className="grid grid-cols-1 gap-x-4 gap-y-2 border-t border-border px-4 py-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <CircleFilter className="sm:w-full" />
        </div>
      </header>
      {view.id === "summary" && <AmcPlanSummaryView />}
      {(view.id === "monthly" || view.id === "weekly") && <AmcPlanTimelineView key={view.id} view={view.id} />}
      {view.id === "current" && <CurrentMonthView />}
    </div>
  );
}

/** Current month detail: management plan file and O&M projection vs GPs converted by AMC date (Management Review page 2). */
function CurrentMonthView() {
  const { period, filters } = useFilters();
  const q = useApiQuery(period ? `amc-conversion:${period.weekId}:${period.compareWeekId}` : null, () =>
    api.getAmcConversion({ weekId: period!.weekId, compareWeekId: period!.compareWeekId }),
  );
  const r = q.data && scoped(q.data, filters.circle);
  if (q.error)
    return (
      <Card>
        <ErrorState error={q.error} onRetry={q.reload} />
      </Card>
    );
  return (
    <>
      {r && (
        <p className="text-sm text-muted-foreground">
          Execution up to {formatDate(r.cutoff)} ({r.week.label}){r.planSource ? ` · plan: ${r.planSource}` : ""}
        </p>
      )}
      {r && r.warnings.length > 0 && (
        <div role="status" className="space-y-1 rounded-lg border border-warning/50 bg-warning-soft px-4 py-3 text-sm text-warning-text">
          {r.warnings.map((w) => (
            <p key={w}>⚠ {w}</p>
          ))}
        </div>
      )}
      <Headline r={r} loading={!r} />
      {r && (
        <>
          <CurrentMonth r={r} />
          <AmcConversionCards cc={r.circleCards} />
        </>
      )}
      {r && (
        <TableCard title="How the figures are calculated">
          <ul className="space-y-2 text-sm">
            {r.definitions.map((d) => (
              <li key={d} className="flex gap-2">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
                {d}
              </li>
            ))}
          </ul>
        </TableCard>
      )}
    </>
  );
}

/** The payload narrowed to one state (state filter): its roadmap row becomes the headline, table and card. */
function scoped(r: R, circle: string | undefined): R {
  const row = circle ? r.roadmap.rows.find((x) => x.id === circle) : undefined;
  if (!row) return r;
  const under = row.cumulativeMtd ?? 0;
  const scope = row.revisedScope ?? 0;
  const plans = r.monthly.rows.find((x) => x.id === circle)?.months.map((m) => m.plan).filter((v): v is number => v != null) ?? [];
  return {
    ...r,
    headline: {
      ...r.headline,
      revisedScope: scope,
      underAmc: under,
      underAmcPct: scope ? Math.round((under / scope) * 10000) / 100 : null,
      monthPlan: row.mtdPlan,
      monthAchieved: row.mtdAchieved,
      monthAchievedPct: row.mtdPlan && row.mtdAchieved != null ? Math.round((row.mtdAchieved / row.mtdPlan) * 10000) / 100 : null,
      projection: row.projection,
      projectionGap: row.gap,
      pendingScope: scope - under,
      totalPlan: plans.length ? plans.reduce((a, b) => a + b, 0) : null,
    },
    roadmap: { ...r.roadmap, rows: [], total: row },
    circleCards: { ...r.circleCards, cards: r.circleCards.cards.filter((c) => c.id === circle) },
  };
}

/* ------------------------------------------------------------------ headline */

function Headline({ r, loading }: { r: R | undefined; loading: boolean }) {
  const h = r?.headline;
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <StatCard
        loading={loading}
        icon={Wrench}
        tone="var(--series-2)"
        label="GPs under AMC"
        info="GPs with an AMC date on or before the cutoff (AMC + incremental), out of the revised existing scope."
        value={formatCount(h?.underAmc)}
        unit={h ? `of ${formatCount(h.revisedScope)}` : undefined}
        caption={h ? `${formatPercent(h.underAmcPct)} of revised scope` : undefined}
      />
      <StatCard
        loading={loading}
        icon={Target}
        tone="var(--series-1)"
        label={r ? `${r.monthLabel} plan vs executed` : "Month plan vs executed"}
        info="Management plan for the month vs GPs whose AMC date falls in the month up to the cutoff."
        value={formatCount(h?.monthAchieved)}
        unit={h ? `of ${dash(h.monthPlan)} planned` : undefined}
        caption={h ? `${h.monthAchievedPct == null ? "NA" : formatPercent(h.monthAchievedPct, 1)} executed · ${r!.daysLeft} days left in the month` : undefined}
      />
      <StatCard
        loading={loading}
        icon={CalendarRange}
        tone="var(--series-7)"
        label="Gap to O&M projection"
        info="O&M “Target for Operational GP” for the month minus the GPs under AMC (never below 0)."
        value={dash(h?.projectionGap)}
        unit="GPs"
        caption={h?.projection != null ? `Projection ${formatCount(h.projection)} GPs under AMC` : "No O&M projection for this month"}
      />
      <StatCard
        loading={loading}
        icon={Hourglass}
        tone="var(--serious)"
        label="Pending scope"
        info="Revised existing GPs not yet under AMC."
        value={formatCount(h?.pendingScope)}
        unit="GPs"
        caption={h?.totalPlan != null ? `${formatCount(h.totalPlan)} GPs planned across ${r!.monthly.months.length} months` : undefined}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ current month detail (same as Management Review page 2) */

function CurrentMonth({ r }: { r: R }) {
  const rm = r.roadmap;
  const cols = [
    ["revisedScope", "Revised scope"],
    ["amcTillPrevMonth", rm.columns.amcTillPrevMonth],
    ["mtdPlan", rm.columns.mtdPlan],
    ["planByMonth", rm.columns.planByMonth],
    ["cumulativeMtd", rm.columns.cumulativeMtd],
    ["mtdAchieved", `${r.monthLabel} executed`],
    ["projection", rm.columns.projection],
    ["projectedCoveragePct", rm.columns.projectedCoveragePct],
    ["gap", rm.columns.gap],
    ["pendingAfterMonth", rm.columns.pendingAfterMonth],
    ["readyForIncremental", rm.columns.readyForIncremental],
  ] as const;
  const value = (x: (typeof rm.rows)[number], k: (typeof cols)[number][0]) => (k === "projectedCoveragePct" ? (x[k] == null ? "—" : formatPercent(x[k])) : dash(x[k]));
  return (
    <TableCard title={rm.planHeader} description="Same figures as Management Review → Target & Achievement">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[980px] text-[13px]">
          <caption className="sr-only">{rm.planHeader}</caption>
          <thead>
            <tr className={HEAD_ROW}>
              <Th first className="align-bottom">
                State
              </Th>
              {cols.map(([k, label]) => (
                <Th key={k} className="min-w-[88px] whitespace-normal align-bottom leading-tight">
                  {label}
                </Th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {rm.rows.map((x) => (
              <tr key={x.id} className={BODY_ROW}>
                <RowHead>{x.name}</RowHead>
                {cols.map(([k]) => (
                  <Td key={k}>{value(x, k)}</Td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot className="tabular">
            <tr className={TOTAL_ROW}>
              <RowHead total>{rm.total.name === "Overall" ? "Total" : rm.total.name}</RowHead>
              {cols.map(([k]) => (
                <Td key={k}>{value(rm.total, k)}</Td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>
    </TableCard>
  );
}
