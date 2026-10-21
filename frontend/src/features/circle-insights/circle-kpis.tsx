"use client";

import { Activity, AlertOctagon, Boxes, Cable, CircleCheckBig, Gauge, Map, ShieldCheck, Users, Wrench } from "lucide-react";
import { StatCard } from "@/components/kpi/stat-card";
import { useFilters } from "@/hooks/use-filters";
import type { CircleInsightsResponse, KpiListKind } from "@/lib/api";
import { KPI_LIST_PATH, KPI_LISTS, kpiListHref } from "@/lib/kpi-lists";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { formatCount, formatDate } from "@/lib/utils/format";

type Summary = NonNullable<CircleInsightsResponse["summary"]>;

const rkm = (v: number | null | undefined) => (v == null ? "NA" : v.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const pct = (a: number, b: number) => (b ? `${((a / b) * 100).toFixed(1)}%` : "NA");

/**
 * Ten headline KPIs of a state, in three rows:
 *  1. simple counts – districts, blocks, HOTO GPs, HOTO blocks
 *  2. composite cards with a breakdown – GPs, fibre route, AMC
 *  3. uptime (MTD) – GPs above 98%, GPs at 0%, penalty-prone blocks (same rules as the O&M sheet and the Circle Overview)
 */
export function CircleKpis({ s, loading, stateName, asOf, circleId }: { s?: Summary; loading: boolean; stateName?: string; asOf?: string; circleId?: string }) {
  const L = loading || !s;
  const { hrefTo } = useFilters();
  // Click a card -> the list behind it for this state only (same week); Back returns to this page.
  const list = (kind: KpiListKind) =>
    circleId ? { href: kpiListHref(hrefTo(KPI_LIST_PATH, { circle: circleId, district: undefined, block: undefined, gp: undefined }), kind, "circle"), linkLabel: KPI_LISTS[kind].linkLabel } : {};
  const mtd = asOf ? `Month-to-date up to ${formatDate(asOf)}` : "Month-to-date";
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          loading={L}
          icon={Map}
          tone="var(--series-7)"
          label="Total Districts"
          info={`Districts of ${stateName ?? "the state"} with at least one GP in the master data.`}
          value={formatCount(s?.districts)}
          caption={stateName}
        />
        <StatCard
          loading={L}
          icon={Boxes}
          tone="var(--series-1)"
          label="Total Blocks"
          info="Distinct block codes in the state."
          value={formatCount(s?.blocks)}
          caption={stateName ? `Blocks in ${stateName}` : undefined}
        />
        <StatCard
          loading={L}
          icon={ShieldCheck}
          tone="var(--good)"
          label="HOTO Done (GPs)"
          info="GPs with a HOTO date on or before the reporting week end, out of the revised existing GPs."
          value={formatCount(s?.hotoDoneGps)}
          unit={s ? `of ${formatCount(s.revisedExisting)}` : undefined}
          caption={s ? `${pct(s.hotoDoneGps, s.revisedExisting)} complete · ${formatCount(s.hotoPendingGps)} pending` : undefined}
          {...list("hoto-gps")}
        />
        <StatCard
          loading={L}
          icon={CircleCheckBig}
          tone="var(--series-3)"
          label="HOTO Done Blocks"
          info="Blocks with at least one GP whose HOTO date is on or before the reporting week end."
          value={formatCount(s?.hotoDoneBlocks)}
          unit={s ? `of ${formatCount(s.blocks)}` : undefined}
          caption={s ? `${pct(s.hotoDoneBlocks, s.blocks)} complete · ${formatCount(s.hotoPendingBlocks)} pending` : undefined}
          {...list("hoto-blocks")}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <StatCard
          loading={L}
          icon={Users}
          tone="var(--series-1)"
          label="Total GPs"
          info={
            <>
              <b>Total GPs</b> = existing GPs (GP Wise Data) + new GPs (Master Block sheet).
              <br />
              <b>Revised existing</b> = existing minus GPs converted to Nagar Palika, closed or deducted ({formatCount(s?.convertedOrClosed)}).
            </>
          }
          value={formatCount(s?.totalGps ?? s?.existingGps)}
          unit="GPs"
          total={s?.totalGps}
          bar={[
            { label: "Existing", value: s?.existingGps ?? 0, color: "var(--series-1)" },
            { label: "New", value: s?.newGps ?? 0, color: "var(--series-3)" },
          ]}
          breakdown={[
            { label: "Existing GPs", value: s?.existingGps ?? null, color: "var(--series-1)", showShare: true },
            { label: "New GPs", value: s?.newGps ?? null, color: "var(--series-3)", showShare: true },
            { label: "Revised existing GPs", value: s?.revisedExisting ?? null, color: "var(--series-7)" },
          ]}
        />
        <StatCard
          loading={L}
          icon={Cable}
          tone="var(--series-1)"
          label="Total Fibre Route"
          info={
            <>
              <b>Total</b> = Σ TOTAL RKM of the state&rsquo;s GP rows. <b>BSNL</b> / <b>BBNL</b> = Σ BSNL / BBNL Live KM.
              {s?.rkmPartsDifference ? ` BSNL + BBNL differs from the total by ${rkm(Math.abs(s.rkmPartsDifference))} RKM because some rows' parts do not add up (listed in Data Operations).` : ""}
            </>
          }
          value={rkm(s?.totalRkm)}
          unit="RKM"
          total={s ? s.bsnlRkm + s.bbnlRkm : null}
          bar={[
            { label: "BSNL", value: s?.bsnlRkm ?? 0, color: "var(--series-1)" },
            { label: "BBNL", value: s?.bbnlRkm ?? 0, color: "var(--series-3)" },
          ]}
          breakdown={[
            { label: "BSNL RKM", value: s?.bsnlRkm ?? null, display: rkm(s?.bsnlRkm), color: "var(--series-1)" },
            { label: "BBNL RKM", value: s?.bbnlRkm ?? null, display: rkm(s?.bbnlRkm), color: "var(--series-3)" },
          ]}
        />
        <StatCard
          loading={L}
          icon={Wrench}
          tone="var(--series-2)"
          label="AMC GPs"
          info="GPs whose AMC date is on or before the week end. AMC = original list, Incremental = added by incremental letter, Non-AMC = revised existing GPs not yet under AMC."
          value={formatCount(s?.amcGps)}
          unit={s?.amcPct != null ? `GPs · ${s.amcPct.toFixed(1)}%` : "GPs"}
          total={s?.revisedExisting}
          bar={[
            { label: "AMC", value: s?.amcOriginalGps ?? 0, color: "var(--series-2)" },
            { label: "Incremental", value: s?.incrementalGps ?? 0, color: "var(--series-4)" },
            { label: "Non-AMC", value: s?.nonAmcGps ?? 0, color: "var(--na)" },
          ]}
          breakdown={[
            { label: "AMC (original)", value: s?.amcOriginalGps ?? null, color: "var(--series-2)", showShare: true },
            { label: "Incremental", value: s?.incrementalGps ?? null, color: "var(--series-4)", showShare: true },
            { label: "Non-AMC", value: s?.nonAmcGps ?? null, color: "var(--na)", showShare: true },
          ]}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatCard
          loading={L}
          icon={Activity}
          tone="var(--good)"
          label={`GPs Above ${THRESHOLDS.healthy}% (MTD)`}
          info={`AMC GPs of ${stateName ?? "the state"} with month-to-date availability above ${THRESHOLDS.healthy}% (exactly ${THRESHOLDS.healthy}% counts in the 95–${THRESHOLDS.healthy}% band, as in the O&M sheet). MTD = mean of daily values from the 1st of the month (or the GP's AMC date).`}
          value={formatCount(s?.gpsAbove98)}
          unit="GPs"
          caption={s ? `${mtd} · of ${formatCount(s.amcGps)} AMC GPs` : mtd}
          {...list("gps-above-98")}
        />
        <StatCard
          loading={L}
          icon={AlertOctagon}
          tone="var(--critical)"
          label="GPs at 0% (MTD)"
          info="AMC GPs with exactly 0% month-to-date availability. GPs that did not report (NA) are counted separately, never as 0%."
          value={formatCount(s?.gpsAtZero)}
          unit="GPs"
          caption={s ? `${mtd} · ${formatCount(s.naGps)} not reported (NA)` : mtd}
          {...list("gps-at-zero")}
        />
        <StatCard
          loading={L}
          icon={Gauge}
          tone="var(--serious)"
          label={`Penalty-Prone Blocks <${THRESHOLDS.penalty}%`}
          info={`Blocks of ${stateName ?? "the state"} whose average AMC GP month-to-date availability is below ${THRESHOLDS.penalty}% (O&M "Penalty Prone Blocks <${THRESHOLDS.penalty}%").`}
          value={formatCount(s?.penaltyBlocks)}
          unit="Blocks"
          caption={s ? `${mtd} · of ${formatCount(s.blocks)} blocks` : mtd}
          {...list("penalty-blocks")}
        />
      </div>
    </div>
  );
}
