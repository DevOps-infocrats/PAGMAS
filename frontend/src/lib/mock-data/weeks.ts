import type { ReportingWeek } from "@/types";

/** Demo reporting window: ISO weeks 30–41 of 2026 (Week 41 = 05–11 Oct 2026). */
export const FIRST_WEEK = 30;
export const LATEST_WEEK = 41;
const YEAR = 2026;
const WEEK_41_MONDAY = Date.UTC(2026, 9, 5);
const DAY = 86_400_000;

const iso = (ms: number) => new Date(ms).toISOString().slice(0, 10);

export const weekId = (n: number) => `${YEAR}-W${String(n).padStart(2, "0")}`;

export function weekStart(n: number): string {
  return iso(WEEK_41_MONDAY - (LATEST_WEEK - n) * 7 * DAY);
}

export function weekEnd(n: number): string {
  return iso(WEEK_41_MONDAY - (LATEST_WEEK - n) * 7 * DAY + 6 * DAY);
}

export function buildWeeks(): ReportingWeek[] {
  const weeks: ReportingWeek[] = [];
  for (let n = FIRST_WEEK; n <= LATEST_WEEK; n++) {
    weeks.push({
      id: weekId(n),
      number: n,
      year: YEAR,
      label: `Week ${n}`,
      startDate: weekStart(n),
      endDate: weekEnd(n),
    });
  }
  return weeks;
}

export function addYears(isoDate: string, years: number): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() + years);
  return iso(d.getTime());
}
