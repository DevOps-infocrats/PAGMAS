/**
 * Shared domain types. These mirror the JSON the FastAPI backend is
 * expected to return (after snake_case → camelCase mapping in lib/api).
 */

export type Role = "admin" | "viewer";

export interface ReportingWeek {
  /** e.g. "2026-W41" */
  id: string;
  /** ISO week number */
  number: number;
  year: number;
  label: string;
  /** ISO dates (YYYY-MM-DD), Monday → Sunday */
  startDate: string;
  endDate: string;
}

export interface Circle {
  id: string;
  code: string;
  name: string;
}

export interface District {
  id: string;
  circleId: string;
  name: string;
  areaManagerId?: string;
}

export interface AreaManager {
  id: string;
  circleId: string;
  /** Demo label only – never a real person */
  label: string;
}

export interface Olt {
  id: string;
  blockId: string;
  location: string;
  ponPorts: number | null;
}

export interface Block {
  id: string;
  code: string;
  circleId: string;
  districtId: string;
  name: string;
  oltIds: string[];
}

export type HotoStatus = "DONE" | "PENDING" | "NOT_APPLICABLE";
export type AmcStatus = "AMC" | "NON_AMC";
export type GpClassification = "EXISTING" | "INCREMENTAL";
export type GpLifecycle = "ACTIVE" | "CONVERTED_NP" | "PERMANENTLY_CLOSED" | "DEDUCTED";

/** One weekly availability snapshot. `value === null` means not reported (NA), distinct from 0%. */
export interface AvailabilityPoint {
  weekId: string;
  date: string;
  value: number | null;
}

export interface DataQualityIssue {
  code: string;
  message: string;
  weekId?: string;
  severity: "info" | "warning" | "critical";
}

/** Static GP record (source-of-truth attributes, not a weekly snapshot). */
export interface Gp {
  id: string;
  lgdCode: string;
  name: string;
  circleId: string;
  districtId: string;
  blockId: string;
  classification: GpClassification;
  /** ISO week number the GP entered scope (incremental GPs only). */
  addedWeek: number | null;
  revisedExisting: boolean;
  lifecycle: GpLifecycle;
  lifecycleWeek: number | null;
  hotoApplicable: boolean;
  hotoWeek: number | null;
  amcStartWeek: number | null;
  amcEndDate: string | null;
  bsnlRkm: number;
  bbnlRkm: number;
  oltId: string | null;
  oneTimeUpSept26: boolean;
  /** Keyed by week id; missing key = GP not monitored that week. */
  availability: Record<string, number | null>;
}

/** A GP resolved for a reporting week (what tables and detail pages render). */
export interface GpSnapshot {
  id: string;
  lgdCode: string;
  name: string;
  circleId: string;
  circleName: string;
  districtId: string;
  districtName: string;
  blockId: string;
  blockName: string;
  classification: GpClassification;
  lifecycle: GpLifecycle;
  hotoStatus: HotoStatus;
  hotoDate: string | null;
  amcStatus: AmcStatus;
  amcStartDate: string | null;
  amcEndDate: string | null;
  bsnlRkm: number;
  bbnlRkm: number;
  totalRkm: number;
  /** MTD availability %, null = NA (not monitored / not reported) */
  availability: number | null;
  oltId: string | null;
  oltLocation: string | null;
  /** Live data extras */
  amcCategory?: "AMC" | "INCREMENTAL" | null;
  locationCode?: string | null;
  weeklyAvailability?: number | null;
  phase?: string | null;
  lot?: string | null;
  amName?: string | null;
  ba?: string | null;
  gpType?: string | null;
}

export type MetricUnit = "count" | "percent" | "rkm";

/** "up" = higher is better, "down" = lower is better, "neutral" = no judgement */
export type MetricPolarity = "up" | "down" | "neutral";

export interface MetricDefinition {
  key: string;
  label: string;
  unit: MetricUnit;
  polarity: MetricPolarity;
  description: string;
  /** Short unit suffix, e.g. "GPs", "Blocks" */
  suffix?: string;
}

export interface KpiValue {
  key: string;
  value: number | null;
  previous: number | null;
  /** Weekly history oldest → newest, aligned with `weeks` on the parent payload */
  history: (number | null)[];
}

export interface TrendSeries {
  name: string;
  points: { weekId: string; date: string; value: number | null }[];
}

export interface CategoryDatum {
  id: string;
  label: string;
  values: Record<string, number | null>;
}

export interface BlockSummary {
  id: string;
  name: string;
  code: string;
  districtId: string;
  districtName: string;
  totalGps: number;
  hotoDone: number;
  hotoPending: number;
  amcGps: number;
  availability: number | null;
  totalRkm: number;
  revisedExisting?: number;
  existingGps?: number;
  newGps?: number | null;
}

export interface CircleSummary {
  id: string;
  name: string;
  code: string;
  districts: number;
  blocks: number;
  totalGps: number;
  hotoDoneBlocks: number;
  hotoDoneGps: number;
  amcGps: number;
  amcPct: number | null;
  availability: number | null;
  gpsAbove98: number;
  gpsAtZero: number;
  naGps: number;
  penaltyBlocks: number;
  incrementalGps: number;
  convertedNp: number;
  permanentlyClosed: number;
  bsnlRkm: number;
  bbnlRkm: number;
  revisedExisting?: number;
  deductedGps?: number;
  amcRkm?: number;
  oneTimeUp?: number;
}

export interface IngestionRun {
  id: string;
  fileName: string;
  startedAt: string | null;
  durationSec: number | null;
  status: "SUCCESS" | "PARTIAL" | "FAILED" | "PROCESSING";
  accepted: number;
  rejected: number;
  validationErrors: { row: number; column: string; message: string; code?: string; gpCode?: string | null }[];
  message?: string | null;
  dataAsOf?: string | null;
  isActive?: boolean;
  issueCounts?: { critical: number; warning: number; info: number };
  /** An upload report (changes vs the previous upload) exists for this run */
  hasReport?: boolean;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface DemoNotification {
  id: string;
  title: string;
  body: string;
  severity: "info" | "warning" | "critical";
  href?: string;
}
