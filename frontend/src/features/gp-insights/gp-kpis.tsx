"use client";

import {
  Activity,
  Boxes,
  Cable,
  CircleCheckBig,
  MapPin,
  Router,
  Wrench,
} from "lucide-react";
import { InfoTip } from "@/components/feedback/badges";
import { StatCard } from "@/components/kpi/stat-card";
import type { GpDetailResponse } from "@/lib/api";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatDate, formatPercent } from "@/lib/utils/format";

const rkm = (v: number | null | undefined) =>
  v == null
    ? "NA"
    : v.toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
const share = (a: number, b: number) =>
  b ? `${((a / b) * 100).toFixed(1)}%` : "–";

/** Compact KPI tile for a single attribute (status, OLT, phase, LOT). */
function Tile({
  icon: Icon,
  tone,
  label,
  info,
  value,
  valueClass,
  caption,
}: {
  icon: React.ComponentType<{ className?: string }>;
  tone: string;
  label: string;
  info: string;
  value: React.ReactNode;
  valueClass?: string;
  caption?: React.ReactNode;
}) {
  return (
    <div className="relative flex min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-card px-4 py-2.5 shadow-xs">
      <span className="absolute inset-x-0 top-0 h-[3px]" style={{ background: tone }} aria-hidden />
      <div className="flex items-center gap-2">
        <span
          className="flex size-7 shrink-0 items-center justify-center rounded-lg"
          style={{
            background: `color-mix(in srgb, ${tone} 12%, transparent)`,
            color: tone,
          }}
          aria-hidden
        >
          <Icon className="size-3.5" />
        </span>
        <span className="whitespace-nowrap text-[13px] font-bold text-subheading">
          {label}
        </span>
        <InfoTip label={label} content={info} />
      </div>
      <p
        className={cn(
          "mt-1 text-lg font-bold leading-tight tracking-tight",
          valueClass,
        )}
      >
        {value}
      </p>
      {caption && (
        <p className="mt-1 text-xs text-muted-foreground">{caption}</p>
      )}
    </div>
  );
}

const NotAvailable = () => <span className="text-muted-foreground">Not Available</span>;

/**
 * KPIs of one GP:
 *  row 1 – Gram Panchayat details (GP + block), block HOTO status, GP HOTO status
 *  row 2 – AMC category (AMC original / Incremental / Non-AMC), OLT location
 *  row 3 – fibre route and availability (unchanged)
 */
export function GpKpis({ d }: { d: GpDetailResponse }) {
  const gp = d.gp;
  const cols = d.uptime?.columns ?? [];
  const td = cols.find((c) => c.kind === "mtd");
  const weeks = cols.filter((c) => c.kind === "week"); // newest first
  const lastMonth = cols.filter((c) => c.kind === "month").at(-1);
  const amc = gp.amcStatus === "AMC";
  const mtd = gp.availability;
  const tone =
    mtd == null
      ? undefined
      : mtd > THRESHOLDS.healthy
        ? "var(--good)"
        : mtd >= THRESHOLDS.penalty
          ? "var(--warning)"
          : "var(--critical)";
  const pct = (v: number | "NA" | null | undefined) =>
    v === "NA" ? "NA" : typeof v === "number" ? formatPercent(v, 2) : "—";
  const parts = gp.bsnlRkm + gp.bbnlRkm;

  const hoto =
    gp.hotoStatus === "DONE"
      ? {
          value: "Done",
          cls: "text-good-text",
          caption: `Handed over on ${formatDate(gp.hotoDate)}`,
        }
      : gp.hotoStatus === "PENDING"
        ? {
            value: "Pending",
            cls: "text-warning-text",
            caption: "No HOTO date on or before the week end",
          }
        : {
            value: "Not applicable",
            cls: "text-muted-foreground",
            caption: "GP converted / closed / deducted",
          };
  // Block-level HOTO (from the backend: at least one GP of the block handed over by the week end).
  const bh = d.blockHoto;
  const blockHoto = !bh
    ? { value: "Not Available", cls: "text-muted-foreground", caption: "Block HOTO status not provided" }
    : bh.done
      ? { value: "Completed", cls: "text-good-text", caption: `${bh.hotoDoneGps} of ${bh.totalGps} GPs of ${gp.blockName} handed over` }
      : { value: "Pending", cls: "text-warning-text", caption: `No GP of ${gp.blockName} handed over yet (${bh.totalGps} GPs)` };
  const gpHoto = { ...hoto, value: hoto.value === "Done" ? "Completed" : hoto.value };

  const amcCat = !amc
    ? {
        value: "Non-AMC",
        cls: "text-muted-foreground",
        caption: d.revisedExisting
          ? "Not yet under AMC on the week end"
          : "Not in revised existing GPs",
      }
    : gp.amcCategory === "INCREMENTAL"
      ? {
          value: "Incremental",
          cls: "text-[color:var(--series-4)]",
          caption: `Under AMC from ${formatDate(gp.amcStartDate)} (incremental letter)`,
        }
      : {
          value: "AMC (original)",
          cls: "text-[color:var(--series-2)]",
          caption: `Under AMC from ${formatDate(gp.amcStartDate)}`,
        };

  return (
    <div className="space-y-3">
      {/* Row 1: GP identification and HOTO status (block-level and GP-level kept apart) */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Tile
          icon={MapPin}
          tone="var(--series-1)"
          label="Gram Panchayat Details"
          info="Gram Panchayat and the block it belongs to (GP Wise Data)."
          value={<span className="block truncate" title={gp.name}>{gp.name}</span>}
          caption={
            <>
              Block: <b className="font-semibold text-foreground">{gp.blockName}</b> · {gp.districtName}, {gp.circleName} · GP code {gp.id}
            </>
          }
        />
        <Tile
          icon={Boxes}
          tone="var(--series-3)"
          label="Block HOTO Status"
          info="Block level: the block's HOTO is completed when at least one of its GPs has a HOTO date on or before the reporting week end (same rule as HOTO Done Blocks)."
          value={blockHoto.value}
          valueClass={blockHoto.cls}
          caption={blockHoto.caption}
        />
        <Tile
          icon={CircleCheckBig}
          tone="var(--good)"
          label="GP HOTO Status"
          info="GP level: this GP's HOTO is completed when its HOTO date is on or before the reporting week end."
          value={gpHoto.value}
          valueClass={gpHoto.cls}
          caption={gpHoto.caption}
        />
      </div>

      {/* Row 2: AMC classification and OLT location */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Tile
          icon={Wrench}
          tone="var(--series-2)"
          label="AMC Category"
          info="AMC (original) = GP from the original AMC list; Incremental = added by the incremental AMC letter; Non-AMC = not yet under AMC on the week end."
          value={amcCat.value}
          valueClass={amcCat.cls}
          caption={amcCat.caption}
        />
        <Tile
          icon={Router}
          tone="var(--series-7)"
          label="OLT Location"
          info="OLT location recorded for this GP in GP Wise Data."
          value={gp.oltLocation ?? <NotAvailable />}
          caption={gp.oltLocation ? `${gp.blockName} block` : "Blank in the source"}
        />
      </div>

      {/* Row 3: fibre route and availability (unchanged) */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <StatCard
          compact
          dense
          layout="split"
          icon={Cable}
          tone="var(--series-1)"
          label="Total Fibre Route"
          info={
            <>
              <b>Total</b> = TOTAL RKM of this GP in GP Wise Data. <b>BSNL</b> /{" "}
              <b>BBNL</b> = BSNL / BBNL Live KM.
              {Math.abs(parts - gp.totalRkm) >= 0.01
                ? ` BSNL + BBNL (${rkm(parts)}) differs from the total by ${rkm(Math.abs(parts - gp.totalRkm))} RKM in the source.`
                : ""}
            </>
          }
          value={rkm(gp.totalRkm)}
          unit="RKM"
          caption="Route kilometres of this GP"
          total={parts}
          bar={[
            { label: "BSNL", value: gp.bsnlRkm, color: "var(--series-1)" },
            { label: "BBNL", value: gp.bbnlRkm, color: "var(--series-3)" },
          ]}
          breakdown={[
            {
              label: "BSNL RKM",
              value: gp.bsnlRkm,
              display: `${rkm(gp.bsnlRkm)} · ${share(gp.bsnlRkm, parts)}`,
              color: "var(--series-1)",
            },
            {
              label: "BBNL RKM",
              value: gp.bbnlRkm,
              display: `${rkm(gp.bbnlRkm)} · ${share(gp.bbnlRkm, parts)}`,
              color: "var(--series-3)",
            },
          ]}
        />
        <StatCard
          compact
          dense
          layout="split"
          icon={Activity}
          tone={tone ?? "var(--na)"}
          label="Availability"
          info={`Headline = month-to-date availability (average of daily values from the later of the month start and the AMC date, up to the data date). Weeks = the workbook's weekly W-nn columns; month = the monthly AMC column. Healthy > ${THRESHOLDS.healthy}%, penalty below ${THRESHOLDS.penalty}%. NA = not reported – never 0%.`}
          value={
            !amc ? "Not under AMC" : mtd == null ? "NA" : formatPercent(mtd, 2)
          }
          caption={
            !amc ? (
              "Availability is tracked from the AMC date"
            ) : (
              <>
                {td
                  ? `${td.label.replace(" TD", "")} month to date`
                  : "Month to date"}
                {d.dataAsOf ? ` · data as of ${formatDate(d.dataAsOf)}` : ""}
              </>
            )
          }
          breakdown={
            amc
              ? [
                  ...(weeks[0]
                    ? [
                        {
                          label: `This week (${weeks[0].label.replace("Till ", "")})`,
                          value: null,
                          display: pct(weeks[0].value),
                        },
                      ]
                    : []),
                  ...(weeks[1]
                    ? [
                        {
                          label: `Last week (${weeks[1].label.replace("WK-", "W-")})`,
                          value: null,
                          display: pct(weeks[1].value),
                        },
                      ]
                    : []),
                  ...(lastMonth
                    ? [
                        {
                          label: `Last month (${lastMonth.label})`,
                          value: null,
                          display: pct(lastMonth.value),
                        },
                      ]
                    : []),
                  ...(td
                    ? [
                        {
                          label: "Block average (MTD)",
                          value: null,
                          display: pct(td.blockAverage),
                        },
                      ]
                    : []),
                ]
              : undefined
          }
        />
      </div>
    </div>
  );
}
