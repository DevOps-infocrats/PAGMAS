"use client";

import { Download, Loader2, Printer } from "lucide-react";
import { useState } from "react";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { BlockFilter, CircleFilter, DistrictFilter, FilterBar } from "@/components/filters/filter-bar";
import { useMeta } from "@/components/providers/data-provider";
import { ReportPreview } from "@/components/reports/report-preview";
import { Button } from "@/components/ui/button";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { api } from "@/lib/api";
import { downloadWeeklyReportPdf } from "@/lib/reports/report-service";

/** Weekly comparison report (circle / district / block scope) – the "Weekly Report" tab of Management Review. */
export function WeeklyReportPanel() {
  const { filters, period } = useFilters();
  const params = period
    ? { weekId: period.weekId, compareWeekId: period.compareWeekId, circleId: filters.circle, districtId: filters.district, blockId: filters.block }
    : null;
  const key = params ? `report:${JSON.stringify(params)}` : null;
  const q = useApiQuery(key, () => api.getWeeklyReport(params!));
  const [downloading, setDownloading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const download = async () => {
    if (!params) return;
    setDownloading(true);
    setMessage(null);
    try {
      const name = await downloadWeeklyReportPdf(params);
      setMessage(`Downloaded ${name}.`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-6">
      <FilterBar>
        <CircleFilter />
        <DistrictFilter />
        <BlockFilter />
        <DateRangeFilter />
        <div className="flex items-end gap-2 sm:ml-auto">
          <Button variant="outline" onClick={() => window.print()} disabled={!q.data}>
            <Printer /> Print
          </Button>
          <Button variant="outline" onClick={download} disabled={!q.data || downloading}>
            {downloading ? <Loader2 className="animate-spin" /> : <Download />}
            Weekly PDF
          </Button>
        </div>
      </FilterBar>

      {message && (
        <p role="status" className="rounded-md border border-border bg-card px-4 py-2.5 text-sm text-muted-foreground">
          {message}
        </p>
      )}

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !q.data ? (
        <PageSkeleton />
      ) : (
        <ReportPreview report={q.data} />
      )}
    </div>
  );
}

/**
 * Reporting date range. Reports are weekly, so the dates snap to the weeks
 * that contain them: "To" sets the reporting week, "From" the comparison week.
 */
function DateRangeFilter() {
  const meta = useMeta();
  const { period, setFilters } = useFilters();
  if (!meta || !period) return null;
  const min = meta.weeks[0].startDate;
  const max = meta.weeks[meta.weeks.length - 1].endDate;
  const weekFor = (iso: string) => meta.weeks.find((w) => iso >= w.startDate && iso <= w.endDate);

  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-semibold text-foreground/75">Reporting date range</span>
      <div className="flex items-center gap-2">
        <Input
          type="date"
          aria-label="From date (comparison week)"
          className="w-[150px]"
          min={min}
          max={period.week.startDate}
          value={period.compareWeek.startDate}
          onChange={(e) => {
            const w = weekFor(e.target.value);
            if (w && w.id !== period.weekId) setFilters({ compare: w.id });
          }}
        />
        <span className="text-subtle-foreground">→</span>
        <Input
          type="date"
          aria-label="To date (reporting week)"
          className="w-[150px]"
          min={min}
          max={max}
          value={period.week.endDate}
          onChange={(e) => {
            const w = weekFor(e.target.value);
            if (!w) return;
            const idx = meta.weeks.indexOf(w);
            const compare = period.compareWeek.number < w.number ? period.compareWeekId : meta.weeks[Math.max(0, idx - 1)].id;
            setFilters({ week: w.id, compare });
          }}
        />
      </div>
    </div>
  );
}
