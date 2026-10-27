"use client";

import { Activity, AlertOctagon, Boxes, CircleCheckBig, CircleDashed, Gauge, Globe2, ShieldCheck, Users, Wrench } from "lucide-react";
import { StatCard } from "@/components/kpi/stat-card";
import { useFilters } from "@/hooks/use-filters";
import type { KpiListKind, OverviewResponse } from "@/lib/api";
import { KPI_LIST_PATH, KPI_LISTS, kpiListHref, stateDetailHref, type KpiListGroup } from "@/lib/kpi-lists";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { formatCount, formatDate } from "@/lib/utils/format";

type Detail = NonNullable<OverviewResponse["summary"]>;
type States = NonNullable<OverviewResponse["stateDetails"]>;

const C = {
  blue: "var(--series-1)",
  orange: "var(--series-2)",
  aqua: "var(--series-3)",
  yellow: "var(--series-4)",
  green: "var(--series-6)",
  violet: "var(--series-7)",
  good: "var(--good)",
  critical: "var(--critical)",
  serious: "var(--serious)",
  brand: "var(--primary)",
};

/** The 10 headline KPIs of the Circle Overview, grouped in three rows. Cards with a link open the list behind the number. */
export function OverviewKpis({ s, states, asOf, loading }: { s?: Detail; states?: States; asOf?: string; loading: boolean }) {
  const L = loading || !s;
  const { hrefTo } = useFilters();
  // The cards count all states, so the list opens for all states too (same week as this page).
  const listBase = hrefTo(KPI_LIST_PATH, { circle: undefined, district: undefined, block: undefined, gp: undefined });
  const listHref = (kind: KpiListKind) => kpiListHref(listBase, kind);
  // HOTO cards open done and pending side by side (tabs); Back returns to this summary.
  const hotoHref = (group: KpiListGroup) => stateDetailHref(listBase, group);
  // AMC GPs card opens the AMC GP details page (all AMC GPs, AMC at HOTO, incremental) with its KPI strip.
  const amcHref = stateDetailHref(listBase, "amcGps", "amc-gps");
  const mtd = asOf ? `Month-to-date up to ${formatDate(asOf)}` : "Month-to-date";
  const byState = (pick: (d: States[number]) => number | null) => (states ?? []).map((d) => `${d.name} ${formatCount(pick(d))}`).join(" · ");

  return (
    <div className="space-y-6">
      <KpiRow title="Network scope">
        <StatCard
          compact
          dense
          loading={L}
          className="md:col-span-3"
          icon={Globe2}
          tone={C.brand}
          label="Total States / Circles"
          info="Circles present in the master data (GP Wise Data sheet)."
          value={formatCount(s?.states)}
          caption={(states ?? []).map((d) => d.name).join(" · ")}
        />
        <StatCard
          compact
          dense
          loading={L}
          className="md:col-span-3"
          icon={Boxes}
          tone={C.violet}
          label="Total Blocks"
          info="Distinct block codes across all three states."
          value={formatCount(s?.blocks)}
          caption={byState((d) => d.blocks)}
          href={listHref("all-blocks")}
          linkLabel={KPI_LISTS["all-blocks"].linkLabel}
        />
        <StatCard
          compact
          dense
          loading={L}
          className="md:col-span-6"
          layout="split"
          icon={Users}
          tone={C.blue}
          label="Total GPs"
          info={
            <>
              <b>Total GPs</b> = existing GPs + new GPs (Master Block sheet).
              <br />
              <b>Revised existing</b> = existing GPs minus those converted to Nagar Palika, permanently closed or deducted during portal entry ({formatCount(s?.convertedOrClosed)} GPs).
            </>
          }
          value={formatCount(s?.totalGps ?? s?.existingGps)}
          unit="GPs"
          caption={`Existing ${formatCount(s?.existingGps)} + New ${formatCount(s?.newGps)}`}
          total={s?.totalGps}
          bar={[
            { label: "Existing GPs", value: s?.existingGps ?? 0, color: C.blue },
            { label: "New GPs", value: s?.newGps ?? 0, color: C.aqua },
          ]}
          breakdown={[
            { label: "Existing GPs", value: s?.existingGps ?? null, color: C.blue, showShare: true },
            { label: "New GPs", value: s?.newGps ?? null, color: C.aqua, showShare: true },
            { label: "Revised existing GPs", value: s?.revisedExisting ?? null, color: C.violet },
          ]}
        />
      </KpiRow>

      <KpiRow title="Handover & AMC">
        <StatCard
          compact
          loading={L}
          className="md:col-span-3"
          icon={CircleCheckBig}
          tone={C.green}
          label="HOTO Done Blocks"
          info="Blocks with at least one GP whose HOTO date is on or before the reporting week end."
          value={formatCount(s?.hotoDoneBlocks)}
          unit={`of ${formatCount(s?.blocks)}`}
          caption={s ? `${formatCount(s.hotoPendingBlocks)} blocks pending` : undefined}
          href={hotoHref("hotoBlocks")}
          linkLabel="View done & pending"
        />
        <StatCard
          compact
          loading={L}
          className="md:col-span-3"
          icon={ShieldCheck}
          tone={C.aqua}
          label="HOTO Done GPs"
          info="GPs with a HOTO date on or before the reporting week end. Pending = revised existing GPs without HOTO."
          value={formatCount(s?.hotoDoneGps)}
          unit={`of ${formatCount(s?.revisedExisting)}`}
          caption={s ? `${formatCount(s.hotoPendingGps)} GPs pending` : undefined}
          href={hotoHref("hotoGps")}
          linkLabel="View done & pending"
        />
        <StatCard
          compact
          loading={L}
          className="md:col-span-6"
          layout="split"
          icon={Wrench}
          tone={C.orange}
          label="AMC GPs"
          info={
            <>
              GPs whose AMC date is on or before the week end. <b>AMC</b> = original AMC list, <b>Incremental</b> = added via incremental letter.
              <br />
              <b>Non-AMC</b> = revised existing GPs not yet under AMC.
            </>
          }
          value={formatCount(s?.amcGps)}
          unit="GPs"
          caption={s?.amcPct != null ? `${s.amcPct.toFixed(1)}% of revised existing GPs` : undefined}
          total={s?.revisedExisting}
          bar={[
            { label: "AMC", value: s?.amcOriginalGps ?? 0, color: C.orange },
            { label: "Incremental", value: s?.incrementalGps ?? 0, color: C.yellow },
            { label: "Non-AMC", value: s?.nonAmcGps ?? 0, color: "var(--na)" },
          ]}
          breakdown={[
            { label: "AMC (original)", value: s?.amcOriginalGps ?? null, color: C.orange, showShare: true },
            { label: "Incremental", value: s?.incrementalGps ?? null, color: C.yellow, showShare: true },
            { label: "Non-AMC", value: s?.nonAmcGps ?? null, color: "var(--na)", showShare: true },
          ]}
          href={amcHref}
          linkLabel="View AMC GP details"
        />
      </KpiRow>

      <KpiRow title="Uptime (MTD) & Non-AMC">
        <StatCard
          compact
          loading={L}
          className="md:col-span-3"
          icon={Activity}
          tone={C.good}
          label={`GPs Above ${THRESHOLDS.healthy}% (MTD)`}
          info={`AMC GPs with month-to-date availability above ${THRESHOLDS.healthy}% (exactly ${THRESHOLDS.healthy}% counts in the 95–${THRESHOLDS.healthy}% band, as in the workbook). MTD = mean of daily values from the 1st of the month (or the GP's AMC date) — same formula as the workbook.`}
          value={formatCount(s?.gpsAbove98)}
          unit="GPs"
          caption={mtd}
          href={listHref("gps-above-98")}
          linkLabel={KPI_LISTS["gps-above-98"].linkLabel}
        />
        <StatCard
          compact
          loading={L}
          className="md:col-span-3"
          icon={AlertOctagon}
          tone={C.critical}
          label="GPs at 0% (MTD)"
          info="AMC GPs with exactly 0% month-to-date availability. GPs that did not report (NA) are counted separately, never as 0%."
          value={formatCount(s?.gpsAtZero)}
          unit="GPs"
          caption={s ? `${mtd} · ${formatCount(s.naGps)} not reported (NA)` : mtd}
          href={listHref("gps-at-zero")}
          linkLabel={KPI_LISTS["gps-at-zero"].linkLabel}
        />
        <StatCard
          compact
          loading={L}
          className="md:col-span-3"
          icon={Gauge}
          tone={C.serious}
          label={`Penalty-Prone Blocks <${THRESHOLDS.penalty}%`}
          info={`Blocks whose average AMC GP month-to-date availability is below ${THRESHOLDS.penalty}% (workbook definition "Penalty Prone Blocks <${THRESHOLDS.penalty}%").`}
          value={formatCount(s?.penaltyBlocks)}
          unit="Blocks"
          caption={byState((d) => d.penaltyBlocks)}
          href={listHref("penalty-blocks")}
          linkLabel={KPI_LISTS["penalty-blocks"].linkLabel}
        />
        <StatCard
          compact
          loading={L}
          className="md:col-span-3"
          icon={CircleDashed}
          tone="var(--na)"
          label="Non-AMC GPs"
          info="Revised existing GPs (not converted to NP / closed / deducted) that are not under AMC on the reporting week end. Same figure as the Non-AMC part of the AMC GPs card."
          value={formatCount(s?.nonAmcGps)}
          unit="GPs"
          caption={s && s.revisedExisting ? `${((s.nonAmcGps / s.revisedExisting) * 100).toFixed(1)}% of revised existing GPs` : undefined}
          href={listHref("non-amc-gps")}
          linkLabel={KPI_LISTS["non-amc-gps"].linkLabel}
        />
      </KpiRow>
    </div>
  );
}

function KpiRow({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section aria-label={title} className="space-y-2.5">
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-subtle-foreground">{title}</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-6 xl:grid-cols-12">{children}</div>
    </section>
  );
}
