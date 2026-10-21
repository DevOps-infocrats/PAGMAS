"use client";

import { ChevronDown } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { lineOption } from "@/components/charts/builders";
import { EChart } from "@/components/charts/echart";
import { useChartTheme } from "@/components/charts/use-chart-theme";
import { KpiSkeleton, ChartSkeleton } from "@/components/feedback/states";
import { Card } from "@/components/ui/primitives";
import { metric, SLA_LABEL, THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatDate } from "@/lib/utils/format";
import type { KpiValue, ReportingWeek } from "@/types";
import { CompactMetric, KpiBody } from "./kpi-card";

/**
 * GA4-style hero: up to four KPI scorecards act as tabs; the selected metric's
 * weekly trend is drawn underneath in the same card.
 */
export function KpiTabs({
  kpis,
  weeks,
  compareLabel,
  loading,
}: {
  kpis: KpiValue[] | undefined;
  weeks: ReportingWeek[] | undefined;
  compareLabel?: string;
  loading?: boolean;
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const theme = useChartTheme();
  const baseId = useId();
  const selected = kpis?.find((k) => k.key === selectedKey) ?? kpis?.[0];
  const periodLabel = weeks?.length ? `${weeks[weeks.length - 1].label} (${formatDate(weeks[weeks.length - 1].startDate)} – ${formatDate(weeks[weeks.length - 1].endDate)})` : undefined;

  const option = useMemo(() => {
    if (!selected || !weeks) return null;
    const def = metric(selected.key);
    return lineOption({
      theme,
      dates: weeks.map((w) => w.endDate),
      series: [{ name: def.label, data: selected.history, color: theme.series[0] }],
      unit: def.unit,
      threshold: selected.key === "availability" ? { value: THRESHOLDS.penalty, label: SLA_LABEL } : undefined,
    });
  }, [selected, weeks, theme]);

  if (loading || !kpis || !weeks) {
    return (
      <Card>
        <div className="grid grid-cols-1 divide-y divide-border sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-4 xl:divide-x">
          {Array.from({ length: 4 }, (_, i) => (
            <KpiSkeleton key={i} />
          ))}
        </div>
        <div className="border-t border-border p-4">
          <ChartSkeleton height={240} />
        </div>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <div
        role="tablist"
        aria-label="Key metrics"
        className="grid grid-cols-1 border-b border-border sm:grid-cols-2 xl:grid-cols-4"
      >
        {kpis.map((k, i) => {
          const active = k.key === selected?.key;
          return (
            // A div (not <button>) because the card contains its own info button.
            <div
              key={k.key}
              id={`${baseId}-tab-${k.key}`}
              role="tab"
              tabIndex={active ? 0 : -1}
              aria-selected={active}
              aria-controls={`${baseId}-panel`}
              onClick={() => setSelectedKey(k.key)}
              onKeyDown={(e) => {
                if (e.target !== e.currentTarget) return;
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setSelectedKey(k.key);
                }
                if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                  const next = kpis[(i + (e.key === "ArrowRight" ? 1 : kpis.length - 1)) % kpis.length];
                  setSelectedKey(next.key);
                  document.getElementById(`${baseId}-tab-${next.key}`)?.focus();
                }
              }}
              className={cn(
                "relative cursor-pointer p-5 text-left transition-colors hover:bg-accent/60 focus-visible:z-10",
                i > 0 && "border-t border-border sm:border-t-0",
                i % 2 === 1 && "sm:border-l",
                i >= 2 && "sm:border-t xl:border-t-0",
                i > 0 && "xl:border-l",
                active && "bg-primary-soft/40",
              )}
            >
              {active && <span className="brand-gradient absolute inset-x-0 top-0 h-[3px]" aria-hidden />}
              <KpiBody kpi={k} def={metric(k.key)} compareLabel={compareLabel} periodLabel={periodLabel} />
            </div>
          );
        })}
      </div>
      <div id={`${baseId}-panel`} role="tabpanel" aria-labelledby={selected ? `${baseId}-tab-${selected.key}` : undefined} className="p-4 pt-3">
        {selected && (
          <p className="px-1 pb-1 text-[13px] text-muted-foreground">
            <span className="font-medium text-foreground">{metric(selected.key).label}</span> · weekly trend, last {weeks.length} reporting weeks
          </p>
        )}
        {option && <EChart option={option} height={240} ariaLabel={`${selected ? metric(selected.key).label : ""} weekly trend`} />}
      </div>
    </Card>
  );
}

/** Collapsible grid of secondary metrics (keeps the page uncluttered). */
export function MoreMetrics({
  kpis,
  compareLabel,
  loading,
  defaultOpen = false,
}: {
  kpis: KpiValue[] | undefined;
  compareLabel?: string;
  loading?: boolean;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <Card>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 rounded-lg px-5 py-3.5 text-left hover:bg-accent/50"
      >
        <span className="text-sm font-medium">
          More metrics
          {kpis && <span className="ml-2 text-muted-foreground">{kpis.length}</span>}
        </span>
        <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div id={id} className="grid grid-cols-1 border-t border-border sm:grid-cols-2 lg:grid-cols-4 [&>*]:border-border [&>*]:border-b sm:[&>*:nth-last-child(-n+2)]:border-b-0 lg:[&>*:nth-last-child(-n+4)]:border-b-0">
          {loading || !kpis
            ? Array.from({ length: 4 }, (_, i) => <KpiSkeleton key={i} />)
            : kpis.map((k) => <CompactMetric key={k.key} kpi={k} compareLabel={compareLabel} />)}
        </div>
      )}
    </Card>
  );
}
