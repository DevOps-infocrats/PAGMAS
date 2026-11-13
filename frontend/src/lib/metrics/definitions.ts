import type { MetricDefinition } from "@/types";

/**
 * Single catalogue of metric definitions. Labels, units, polarity and tooltip
 * text all come from here so every page describes a metric the same way.
 */

/** Source-defined thresholds ("Penalty Prone Blocks <90%" in the O&M sheet). The backend sends the same values in /meta. */
export const THRESHOLDS = { healthy: 98, penalty: 90 } as const;
export const SLA_LABEL = `SLA ${THRESHOLDS.penalty}%`;
const P = THRESHOLDS.penalty;
const MTD_NOTE = "Compared with the MTD at the end of the comparison week – if that week ends in the first days of a month its MTD covers only those days; use the (Week) metrics for like-for-like comparison.";

const list: MetricDefinition[] = [
  { key: "totalStates", label: "Total States", unit: "count", polarity: "neutral", suffix: "States", description: "Circles/states present in the master data." },
  { key: "totalDistricts", label: "Total Districts", unit: "count", polarity: "neutral", suffix: "Districts", description: "Districts with at least one GP in the master data." },
  { key: "totalBlocks", label: "Total Blocks", unit: "count", polarity: "neutral", suffix: "Blocks", description: "Distinct block codes in the master data." },
  { key: "totalGps", label: "Total Existing GPs", unit: "count", polarity: "neutral", suffix: "GPs", description: "Existing GP rows in the master list, including GPs later converted to NP or closed. Each GP is counted once." },
  { key: "revisedExisting", label: "Revised Existing GPs", unit: "count", polarity: "neutral", suffix: "GPs", description: "Existing GPs minus those converted to Nagar Palika, permanently closed or deducted during portal entry." },
  { key: "hotoDoneBlocks", label: "HOTO Done Blocks", unit: "count", polarity: "up", suffix: "Blocks", description: "Blocks with at least one GP whose HOTO date is on or before the reporting week end." },
  { key: "hotoDoneGps", label: "HOTO Done GPs", unit: "count", polarity: "up", suffix: "GPs", description: "GPs with a HOTO date on or before the reporting week end." },
  { key: "hotoPendingGps", label: "HOTO Pending GPs", unit: "count", polarity: "down", suffix: "GPs", description: "Revised existing GPs without a HOTO date by the week end." },
  { key: "amcGps", label: "AMC GPs", unit: "count", polarity: "up", suffix: "GPs", description: "GPs whose AMC date is on or before the week end (original AMC + incremental)." },
  { key: "nonAmcGps", label: "Non-AMC GPs", unit: "count", polarity: "neutral", suffix: "GPs", description: "Revised existing GPs not yet under AMC by the week end." },
  { key: "amcPct", label: "AMC GP Percentage", unit: "percent", polarity: "up", description: "AMC GPs ÷ revised existing GPs. Week-on-week change is shown in percentage points (pp)." },
  { key: "availability", label: "AMC Availability (MTD)", unit: "percent", polarity: "up", description: "Average month-to-date availability of AMC GPs, counted from each GP's AMC date up to the week end (or last data day). NA GPs are excluded, never counted as 0%." },
  { key: "gpsAbove98", label: "GPs Above 98% (MTD)", unit: "count", polarity: "up", suffix: "GPs", description: `AMC GPs with month-to-date availability above 98% (a value of exactly 98% falls in the 95–98% band, as in the workbook). ${MTD_NOTE}` },
  { key: "gpsAtZero", label: "GPs at 0% (MTD)", unit: "count", polarity: "down", suffix: "GPs", description: "AMC GPs with exactly 0% month-to-date availability. NA (not reported) is counted separately." },
  { key: "naGps", label: "NA GPs", unit: "count", polarity: "down", suffix: "GPs", description: "AMC GPs with no availability reported (NA – distinct from 0%)." },
  { key: "penaltyBlocks", label: `Penalty-Prone Blocks (<${P}%)`, unit: "count", polarity: "down", suffix: "Blocks", description: `Blocks whose mean AMC GP month-to-date availability is below ${P}% (source definition: "Penalty Prone Blocks <${P}%"). ${MTD_NOTE}` },
  { key: "availabilityWeek", label: "AMC Availability (Week)", unit: "percent", polarity: "up", description: "Average of the source's weekly AMC availability column for the reporting week. Best for week-on-week comparison." },
  { key: "gpsAbove98Week", label: "GPs Above 98% (Week)", unit: "count", polarity: "up", suffix: "GPs", description: "AMC GPs with weekly availability above 98% (matches the O&M weekly uptime table)." },
  { key: "gpsAtZeroWeek", label: "GPs at 0% (Week)", unit: "count", polarity: "down", suffix: "GPs", description: "AMC GPs with 0% weekly availability." },
  { key: "penaltyBlocksWeek", label: `Penalty-Prone Blocks (Week, <${P}%)`, unit: "count", polarity: "down", suffix: "Blocks", description: `Blocks whose mean weekly AMC availability is below ${P}%.` },
  { key: "oneTimeUp", label: "One-Time UP GPs (Sept-26)", unit: "count", polarity: "up", suffix: "GPs", description: "GPs with September 2026 availability above 0% (all GPs). The O&M sheet's figure comes from an external report and can differ slightly." },
  { key: "totalRkm", label: "Total Scope Fibre", unit: "rkm", polarity: "neutral", description: "Sum of TOTAL RKM for all GP rows (route kilometres)." },
  { key: "amcRkm", label: "AMC Fibre RKM", unit: "rkm", polarity: "up", description: "Sum of TOTAL RKM for AMC GPs." },
  { key: "bsnlRkm", label: "BSNL Existing RKM", unit: "rkm", polarity: "neutral", description: "Sum of BSNL Live KM." },
  { key: "bbnlRkm", label: "BBNL Existing RKM", unit: "rkm", polarity: "neutral", description: "Sum of BBNL Live KM." },
  { key: "incrementalGps", label: "Incremental GPs", unit: "count", polarity: "neutral", suffix: "GPs", description: "AMC GPs whose 'AMC / Incremental' category is Incremental." },
  { key: "convertedNp", label: "Converted to NP", unit: "count", polarity: "down", suffix: "GPs", description: "GPs converted to Nagar Palika (no date recorded in the source)." },
  { key: "permanentlyClosed", label: "Permanently Closed", unit: "count", polarity: "down", suffix: "GPs", description: "GPs permanently closed (no date recorded in the source)." },
  { key: "deductedGps", label: "Deducted GPs", unit: "count", polarity: "neutral", suffix: "GPs", description: "GPs deducted from a block during portal entry." },
];

export const METRICS: Record<string, MetricDefinition> = Object.fromEntries(list.map((m) => [m.key, m]));

export type MetricKey = keyof SummaryMetricsShape;

/** Keys produced by `summarize()` – kept in sync with the catalogue above. */
export interface SummaryMetricsShape {
  totalStates: number;
  totalDistricts: number;
  totalBlocks: number;
  totalGps: number;
  revisedExisting: number;
  hotoDoneBlocks: number;
  hotoDoneGps: number;
  hotoPendingGps: number;
  amcAtHotoGps: number;
  gpsBelowPenalty: number;
  blocksAbove98: number;
  reportingGps: number;
  reportingBlocks: number;
  amcGps: number;
  nonAmcGps: number;
  amcPct: number | null;
  availability: number | null;
  gpsAbove98: number;
  gpsAtZero: number;
  naGps: number;
  penaltyBlocks: number;
  oneTimeUp: number;
  totalRkm: number;
  bsnlRkm: number;
  bbnlRkm: number;
  incrementalGps: number;
  convertedNp: number;
  permanentlyClosed: number;
  amcRkm: number;
  deductedGps: number;
  availabilityWeek?: number | null;
  gpsAbove98Week?: number;
  gpsAtZeroWeek?: number;
  penaltyBlocksWeek?: number;
}

export function metric(key: string): MetricDefinition {
  const m = METRICS[key];
  if (!m) throw new Error(`Unknown metric: ${key}`);
  return m;
}
