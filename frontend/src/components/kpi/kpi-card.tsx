"use client";

import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import { InfoTip } from "@/components/feedback/badges";
import { Card } from "@/components/ui/primitives";
import { metric } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatDelta, formatValue, splitValue } from "@/lib/utils/format";
import type { KpiValue, MetricDefinition } from "@/types";
import { Sparkline } from "./sparkline";

type DeltaTone = "good" | "bad" | "flat";

export function deltaOf(kpi: KpiValue): number | null {
  if (kpi.value == null || kpi.previous == null) return null;
  return Math.round((kpi.value - kpi.previous) * 100) / 100;
}

function toneOf(delta: number | null, def: MetricDefinition): DeltaTone {
  if (delta == null || delta === 0 || def.polarity === "neutral") return "flat";
  const up = delta > 0;
  return (def.polarity === "up") === up ? "good" : "bad";
}

/** ▲/▼ change vs comparison week. Colour = direction × whether that direction is good. */
export function DeltaChip({ kpi, compareLabel, className }: { kpi: KpiValue; compareLabel?: string; className?: string }) {
  const def = metric(kpi.key);
  const delta = deltaOf(kpi);
  if (delta == null) {
    return <span className={cn("text-xs text-subtle-foreground", className)}>No comparison available</span>;
  }
  const tone = toneOf(delta, def);
  const Icon = delta > 0 ? ArrowUpRight : delta < 0 ? ArrowDownRight : ArrowRight;
  const toneClass =
    tone === "good" ? "bg-good-soft text-good-text" : tone === "bad" ? "bg-critical-soft text-critical-text" : "bg-muted text-muted-foreground";
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs", className)}>
      <span className={cn("tabular inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 font-medium", toneClass)}>
        <Icon className="size-3.5" aria-hidden />
        <span className="sr-only">{tone === "good" ? "Improved" : tone === "bad" ? "Worsened" : "Changed"} by </span>
        {formatDelta(delta, def.unit)}
      </span>
      {compareLabel && <span className="text-subtle-foreground">vs {compareLabel}</span>}
    </span>
  );
}

function KpiValueText({ kpi, size }: { kpi: KpiValue; size: "hero" | "compact" }) {
  const def = metric(kpi.key);
  const { num, unit } = splitValue(kpi.value, def.unit);
  const suffix = unit || def.suffix;
  return (
    <p className={cn("flex items-baseline gap-1 font-semibold tracking-tight", size === "hero" ? "text-[28px] leading-9" : "text-xl")}>
      <span className={cn(kpi.value == null && "text-muted-foreground")}>{num}</span>
      {kpi.value != null && suffix && (
        <span className={cn("font-medium text-muted-foreground", size === "hero" ? "text-sm" : "text-xs")}>{suffix}</span>
      )}
    </p>
  );
}

/** Standalone scorecard (GA4 style): label + info, value + unit, delta, sparkline. */
export function KpiCard({
  kpi,
  compareLabel,
  periodLabel,
  className,
}: {
  kpi: KpiValue;
  compareLabel?: string;
  periodLabel?: string;
  className?: string;
}) {
  const def = metric(kpi.key);
  return (
    <Card className={cn("p-5", className)}>
      <KpiBody kpi={kpi} def={def} compareLabel={compareLabel} periodLabel={periodLabel} />
    </Card>
  );
}

export function KpiBody({
  kpi,
  def,
  compareLabel,
  periodLabel,
}: {
  kpi: KpiValue;
  def: MetricDefinition;
  compareLabel?: string;
  periodLabel?: string;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5">
        <span className="truncate text-[13px] font-medium text-muted-foreground">{def.label}</span>
        <InfoTip
          label={def.label}
          content={
            <>
              {def.description}
              {periodLabel && <span className="mt-1 block text-subtle-foreground">Reporting period: {periodLabel}</span>}
            </>
          }
        />
      </div>
      <div className="flex items-end justify-between gap-3">
        <KpiValueText kpi={kpi} size="hero" />
        <Sparkline values={kpi.history} className="mb-1.5 shrink-0" />
      </div>
      <DeltaChip kpi={kpi} compareLabel={compareLabel} />
    </div>
  );
}

/** Compact metric row used in the collapsible "More metrics" grid. */
export function CompactMetric({ kpi, compareLabel }: { kpi: KpiValue; compareLabel?: string }) {
  const def = metric(kpi.key);
  return (
    <div className="flex flex-col gap-1.5 p-4">
      <div className="flex items-center gap-1.5">
        <span className="truncate text-[13px] text-muted-foreground">{def.label}</span>
        <InfoTip label={def.label} content={def.description} />
      </div>
      <KpiValueText kpi={kpi} size="compact" />
      <DeltaChip kpi={kpi} compareLabel={compareLabel} />
    </div>
  );
}

export const kpiText = (kpi: KpiValue) => formatValue(kpi.value, metric(kpi.key).unit);
