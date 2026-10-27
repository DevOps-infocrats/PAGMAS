import type { AmcStatus, Gp, GpLifecycle, HotoStatus } from "@/types";
import { round } from "@/lib/mock-data/random";
import { weekId } from "@/lib/mock-data/weeks";
import { THRESHOLDS, type SummaryMetricsShape } from "./definitions";

/*
 * Pure calculation helpers. UI components never compute metrics themselves;
 * they render what the API layer returns. The live rules live in the
 * Python backend and this module is only used by the mock client.
 */

export const existsAt = (gp: Gp, w: number) => gp.addedWeek == null || gp.addedWeek <= w;

export const lifecycleAt = (gp: Gp, w: number): GpLifecycle =>
  gp.lifecycleWeek != null && gp.lifecycleWeek <= w ? gp.lifecycle : "ACTIVE";

export const hotoAt = (gp: Gp, w: number): HotoStatus =>
  !gp.hotoApplicable ? "NOT_APPLICABLE" : gp.hotoWeek != null && gp.hotoWeek <= w ? "DONE" : "PENDING";

export const amcAt = (gp: Gp, w: number): AmcStatus =>
  gp.amcStartWeek != null && gp.amcStartWeek <= w && lifecycleAt(gp, w) === "ACTIVE" ? "AMC" : "NON_AMC";

/** MTD availability for the week; null = NA (not under AMC or not reported). */
export const availabilityAt = (gp: Gp, w: number): number | null =>
  amcAt(gp, w) === "AMC" ? (gp.availability[weekId(w)] ?? null) : null;

export const mean = (values: number[]): number | null =>
  values.length ? round(values.reduce((a, b) => a + b, 0) / values.length, 2) : null;

export function inScope(gps: Gp[], w: number): Gp[] {
  return gps.filter((g) => existsAt(g, w));
}

/** Average availability of a block's reporting AMC GPs (null if none reported). */
export function blockAvailability(blockGps: Gp[], w: number): number | null {
  const vals: number[] = [];
  for (const g of blockGps) {
    const v = availabilityAt(g, w);
    if (v != null) vals.push(v);
  }
  return mean(vals);
}

export function groupBy<T>(items: T[], key: (t: T) => string): Map<string, T[]> {
  const m = new Map<string, T[]>();
  for (const it of items) {
    const k = key(it);
    const arr = m.get(k);
    if (arr) arr.push(it);
    else m.set(k, [it]);
  }
  return m;
}

/** Computes every summary metric for a set of GPs at a given ISO week. */
export function summarize(allGps: Gp[], w: number): SummaryMetricsShape {
  const gps = inScope(allGps, w);
  const byBlock = groupBy(gps, (g) => g.blockId);
  const circles = new Set<string>();
  const districts = new Set<string>();

  let hotoDoneGps = 0;
  let hotoPendingGps = 0;
  let amcGps = 0;
  let gpsAbove98 = 0;
  let gpsAtZero = 0;
  let gpsBelowPenalty = 0;
  let naGps = 0;
  let oneTimeUp = 0;
  let revisedExisting = 0;
  let incrementalGps = 0;
  let convertedNp = 0;
  let permanentlyClosed = 0;
  let bsnlRkm = 0;
  let bbnlRkm = 0;
  let amcRkm = 0;
  const avail: number[] = [];

  for (const g of gps) {
    circles.add(g.circleId);
    districts.add(g.districtId);
    const hoto = hotoAt(g, w);
    if (hoto === "DONE") hotoDoneGps++;
    if (hoto === "PENDING") hotoPendingGps++;
    const life = lifecycleAt(g, w);
    if (life === "CONVERTED_NP") convertedNp++;
    if (life === "PERMANENTLY_CLOSED") permanentlyClosed++;
    if (g.revisedExisting) revisedExisting++;
    if (g.classification === "INCREMENTAL") incrementalGps++;
    bsnlRkm += g.bsnlRkm;
    bbnlRkm += g.bbnlRkm;
    if (amcAt(g, w) === "AMC") {
      amcGps++;
      amcRkm += g.bsnlRkm + g.bbnlRkm;
      if (g.oneTimeUpSept26) oneTimeUp++;
      const v = availabilityAt(g, w);
      if (v == null) naGps++;
      else {
        avail.push(v);
        if (v >= THRESHOLDS.healthy) gpsAbove98++;
        if (v === 0) gpsAtZero++;
        if (v < THRESHOLDS.penalty) gpsBelowPenalty++;
      }
    }
  }

  let hotoDoneBlocks = 0;
  let penaltyBlocks = 0;
  let blocksAbove98 = 0;
  let reportingBlocks = 0;
  for (const blockGps of byBlock.values()) {
    const applicable = blockGps.filter((g) => g.hotoApplicable);
    if (applicable.length && applicable.every((g) => hotoAt(g, w) === "DONE")) hotoDoneBlocks++;
    const ba = blockAvailability(blockGps, w);
    if (ba != null && ba < THRESHOLDS.penalty) penaltyBlocks++;
    if (ba != null) reportingBlocks++;
    if (ba != null && ba > THRESHOLDS.healthy) blocksAbove98++;
  }

  return {
    totalStates: circles.size,
    totalDistricts: districts.size,
    totalBlocks: byBlock.size,
    totalGps: gps.length,
    revisedExisting,
    hotoDoneBlocks,
    hotoDoneGps,
    hotoPendingGps,
    gpsBelowPenalty,
    blocksAbove98,
    reportingGps: avail.length,
    reportingBlocks,
    amcAtHotoGps: amcGps - incrementalGps, // same rule as the backend: AMC GPs not classified Incremental
    amcGps,
    nonAmcGps: gps.length - amcGps,
    amcPct: gps.length ? round((amcGps / gps.length) * 100, 2) : null,
    availability: mean(avail),
    gpsAbove98,
    gpsAtZero,
    naGps,
    penaltyBlocks,
    oneTimeUp,
    totalRkm: round(bsnlRkm + bbnlRkm, 1),
    bsnlRkm: round(bsnlRkm, 1),
    bbnlRkm: round(bbnlRkm, 1),
    incrementalGps,
    convertedNp,
    permanentlyClosed,
    amcRkm: round(amcRkm, 1),
    deductedGps: 0,
  };
}

export interface BandCounts {
  above98: number;
  from85to98: number;
  below85: number;
  zero: number;
  na: number;
}

/** Availability bands for AMC GPs; zero and NA are separate from "below 85%". */
export function gpBands(allGps: Gp[], w: number): BandCounts {
  const out: BandCounts = { above98: 0, from85to98: 0, below85: 0, zero: 0, na: 0 };
  for (const g of allGps) {
    if (!existsAt(g, w) || amcAt(g, w) !== "AMC") continue;
    const v = availabilityAt(g, w);
    if (v == null) out.na++;
    else if (v === 0) out.zero++;
    else if (v >= THRESHOLDS.healthy) out.above98++;
    else if (v >= THRESHOLDS.penalty) out.from85to98++;
    else out.below85++;
  }
  return out;
}

export function blockBands(allGps: Gp[], w: number): Omit<BandCounts, "zero"> {
  const out = { above98: 0, from85to98: 0, below85: 0, na: 0 };
  for (const blockGps of groupBy(inScope(allGps, w), (g) => g.blockId).values()) {
    const v = blockAvailability(blockGps, w);
    if (v == null) out.na++;
    else if (v >= THRESHOLDS.healthy) out.above98++;
    else if (v >= THRESHOLDS.penalty) out.from85to98++;
    else out.below85++;
  }
  return out;
}
