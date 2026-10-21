import type { MetricUnit } from "@/types";

const intFmt = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const dec1 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const dec2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export const NA_LABEL = "NA";

/** Indian grouping (1,23,456). Null/undefined renders as NA, never as 0. */
export function formatCount(v: number | null | undefined): string {
  return v == null ? NA_LABEL : intFmt.format(v);
}

export function formatPercent(v: number | null | undefined, digits = 1): string {
  if (v == null) return NA_LABEL;
  return `${digits === 2 ? dec2.format(v) : dec1.format(v)}%`;
}

export function formatRkm(v: number | null | undefined): string {
  if (v == null) return NA_LABEL;
  return `${v >= 1000 ? intFmt.format(v) : dec1.format(v)} RKM`;
}

export function formatValue(v: number | null | undefined, unit: MetricUnit): string {
  if (unit === "percent") return formatPercent(v);
  if (unit === "rkm") return formatRkm(v);
  return formatCount(v);
}

/** Splits a formatted value into number + unit for the KPI layout. */
export function splitValue(v: number | null | undefined, unit: MetricUnit): { num: string; unit: string } {
  if (v == null) return { num: NA_LABEL, unit: "" };
  if (unit === "percent") return { num: dec1.format(v), unit: "%" };
  if (unit === "rkm") return { num: v >= 1000 ? intFmt.format(v) : dec1.format(v), unit: "RKM" };
  return { num: intFmt.format(v), unit: "" };
}

/** Absolute change; percentage metrics are expressed in percentage points (pp). */
export function formatDelta(delta: number | null, unit: MetricUnit): string {
  if (delta == null) return NA_LABEL;
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  const abs = Math.abs(delta);
  if (unit === "percent") return `${sign}${dec1.format(abs)} pp`;
  if (unit === "rkm") return `${sign}${dec1.format(abs)} RKM`;
  return `${sign}${intFmt.format(abs)}`;
}

export function formatRelativeChange(current: number | null, previous: number | null): string {
  if (current == null || previous == null || previous === 0) return NA_LABEL;
  const pct = ((current - previous) / previous) * 100;
  const sign = pct > 0 ? "+" : pct < 0 ? "−" : "±";
  return `${sign}${dec1.format(Math.abs(pct))}%`;
}

const dateFmt = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
const shortDateFmt = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", timeZone: "UTC" });

/** Dates are ISO (YYYY-MM-DD) and formatted in UTC so server and client agree. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return NA_LABEL;
  return dateFmt.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`));
}

export function formatShortDate(iso: string): string {
  return shortDateFmt.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`));
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return `${dateFmt.format(d)}, ${d.toISOString().slice(11, 16)} UTC`;
}

export function formatDuration(sec: number | null): string {
  if (sec == null) return NA_LABEL;
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s`;
}
