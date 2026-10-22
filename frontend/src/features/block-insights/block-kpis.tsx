"use client";

import { Cable, CircleCheckBig, CircleDashed, Users, Wrench } from "lucide-react";
import { StatCard } from "@/components/kpi/stat-card";
import { useFilters } from "@/hooks/use-filters";
import type { BlockInsightsResponse } from "@/lib/api";
import { KPI_LIST_PATH, KPI_LISTS, kpiListHref, stateDetailHref } from "@/lib/kpi-lists";
import { formatCount } from "@/lib/utils/format";

type Summary = NonNullable<BlockInsightsResponse["summary"]>;

const rkm = (v: number | null | undefined) =>
  v == null
    ? "NA"
    : v.toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
const pct = (a: number, b: number) =>
  b ? `${((a / b) * 100).toFixed(1)}%` : "NA";

/**
 * Five headline KPIs of one block:
 *  1. GPs (existing / new / revised) and fibre route (BSNL / BBNL)
 *  2. HOTO done (done / pending), AMC (AMC / incremental / non-AMC) and Non-AMC GPs
 * AMC GPs and Non-AMC GPs open the GP lists of this block; Back returns here.
 */
export function BlockKpis({ s, loading }: { s?: Summary; loading: boolean }) {
  const L = loading || !s;
  const { hrefTo } = useFilters();
  // The URL already holds this block's circle / district / block, so the lists open for this block only.
  const listBase = hrefTo(KPI_LIST_PATH, { gp: undefined });
  const notApplicable = s ? s.existingGps - s.revisedExisting : 0;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <StatCard
          compact
          loading={L}
          layout="split"
          icon={Users}
          tone="var(--series-1)"
          label="Total GPs"
          info={
            <>
              <b>Total GPs</b> = existing GPs (GP Wise Data) + new GPs (Master
              Block sheet).
              <br />
              <b>Revised existing</b> = existing minus GPs converted to Nagar
              Palika, closed or deducted ({formatCount(s?.convertedOrClosed)}).
            </>
          }
          value={formatCount(s?.totalGps ?? s?.existingGps)}
          unit="GPs"
          caption="in this block"
          total={s?.totalGps ?? s?.existingGps}
          bar={[
            {
              label: "Existing",
              value: s?.existingGps ?? 0,
              color: "var(--series-1)",
            },
            { label: "New", value: s?.newGps ?? 0, color: "var(--series-3)" },
          ]}
          breakdown={[
            {
              label: "Existing GPs",
              value: s?.existingGps ?? null,
              color: "var(--series-1)",
              showShare: true,
            },
            {
              label: "New GPs",
              value: s?.newGps ?? null,
              color: "var(--series-3)",
              showShare: true,
            },
            {
              label: "Revised existing GPs",
              value: s?.revisedExisting ?? null,
              color: "var(--series-7)",
            },
          ]}
        />
        <StatCard
          compact
          loading={L}
          layout="split"
          icon={Cable}
          tone="var(--series-1)"
          label="Total Fibre Route"
          info={
            <>
              <b>Total</b> = Σ TOTAL RKM of the block&rsquo;s GP rows.{" "}
              <b>BSNL</b> / <b>BBNL</b> = Σ BSNL / BBNL Live KM.
              {s?.rkmPartsDifference
                ? ` BSNL + BBNL differs from the total by ${rkm(Math.abs(s.rkmPartsDifference))} RKM (rounding / rows whose parts do not add up).`
                : ""}
            </>
          }
          value={rkm(s?.totalRkm)}
          unit="RKM"
          caption={s ? `AMC fibre: ${rkm(s.amcRkm)} RKM` : undefined}
          total={s ? s.bsnlRkm + s.bbnlRkm : null}
          bar={[
            { label: "BSNL", value: s?.bsnlRkm ?? 0, color: "var(--series-1)" },
            { label: "BBNL", value: s?.bbnlRkm ?? 0, color: "var(--series-3)" },
          ]}
          breakdown={[
            {
              label: "BSNL RKM",
              value: s?.bsnlRkm ?? null,
              display: `${rkm(s?.bsnlRkm)} · ${s ? pct(s.bsnlRkm, s.bsnlRkm + s.bbnlRkm) : ""}`,
              color: "var(--series-1)",
            },
            {
              label: "BBNL RKM",
              value: s?.bbnlRkm ?? null,
              display: `${rkm(s?.bbnlRkm)} · ${s ? pct(s.bbnlRkm, s.bsnlRkm + s.bbnlRkm) : ""}`,
              color: "var(--series-3)",
            },
          ]}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <StatCard
          compact
          loading={L}
          icon={CircleCheckBig}
          tone="var(--good)"
          label="HOTO Done"
          info="GPs with a HOTO date on or before the reporting week end, out of the revised existing GPs (converted / closed GPs are not applicable)."
          value={formatCount(s?.hotoDoneGps)}
          unit={s ? `of ${formatCount(s.revisedExisting)} GPs` : undefined}
          caption={
            s ? `${pct(s.hotoDoneGps, s.revisedExisting)} complete` : undefined
          }
          total={s?.revisedExisting}
          bar={[
            { label: "Done", value: s?.hotoDoneGps ?? 0, color: "var(--good)" },
            {
              label: "Pending",
              value: s?.hotoPendingGps ?? 0,
              color: "var(--warning)",
            },
          ]}
          breakdown={[
            {
              label: "Done",
              value: s?.hotoDoneGps ?? null,
              color: "var(--good)",
              showShare: true,
            },
            {
              label: "Pending",
              value: s?.hotoPendingGps ?? null,
              color: "var(--warning)",
              showShare: true,
            },
            ...(notApplicable
              ? [
                  {
                    label: "Not applicable (converted / closed)",
                    value: notApplicable,
                    color: "var(--na)",
                  },
                ]
              : []),
          ]}
        />
        <StatCard
          compact
          loading={L}
          icon={Wrench}
          tone="var(--series-2)"
          label="AMC GPs"
          info="GPs whose AMC date is on or before the week end. AMC = original AMC list, Incremental = added by the incremental letter, Non-AMC = revised existing GPs not yet under AMC."
          value={formatCount(s?.amcGps)}
          unit={
            s?.amcPct != null
              ? `of ${formatCount(s.revisedExisting)} · ${s.amcPct.toFixed(1)}%`
              : "GPs"
          }
          href={stateDetailHref(listBase, "amcGps", undefined, "block")}
          linkLabel="View AMC & incremental GPs"
          total={s?.revisedExisting}
          bar={[
            {
              label: "AMC",
              value: s?.amcOriginalGps ?? 0,
              color: "var(--series-2)",
            },
            {
              label: "Incremental",
              value: s?.incrementalGps ?? 0,
              color: "var(--series-4)",
            },
            { label: "Non-AMC", value: s?.nonAmcGps ?? 0, color: "var(--na)" },
          ]}
          breakdown={[
            {
              label: "AMC (original)",
              value: s?.amcOriginalGps ?? null,
              color: "var(--series-2)",
              showShare: true,
            },
            {
              label: "Incremental",
              value: s?.incrementalGps ?? null,
              color: "var(--series-4)",
              showShare: true,
            },
            {
              label: "Non-AMC",
              value: s?.nonAmcGps ?? null,
              color: "var(--na)",
              showShare: true,
            },
          ]}
        />
        <StatCard
          compact
          loading={L}
          icon={CircleDashed}
          tone="var(--na)"
          label="Non-AMC GPs"
          info="Revised existing GPs of the block (not converted to NP / closed / deducted) that are not under AMC on the reporting week end. Same figure as the Non-AMC part of the AMC GPs card."
          value={formatCount(s?.nonAmcGps)}
          unit={s ? `of ${formatCount(s.revisedExisting)} GPs` : "GPs"}
          caption={
            s && s.revisedExisting
              ? `${pct(s.nonAmcGps, s.revisedExisting)} of revised existing GPs not yet under AMC`
              : undefined
          }
          href={kpiListHref(listBase, "non-amc-gps", "block")}
          linkLabel={KPI_LISTS["non-amc-gps"].linkLabel}
        />
      </div>
    </div>
  );
}
