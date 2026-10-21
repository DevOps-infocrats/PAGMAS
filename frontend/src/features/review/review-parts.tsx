"use client";

import { ArrowRight, Minus, TrendingDown, TrendingUp } from "lucide-react";
import { createContext, useContext } from "react";
import type { ReviewChange, ReviewInsight, ReviewPeriod } from "@/lib/api";
import { Select } from "@/components/ui/overlays";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatPercent } from "@/lib/utils/format";

/* Shared pieces of the Management Review page (same figures as the PPT deck). */

/** True inside presentation mode: dense pages switch to a slide layout (same data, laid out to fit 16:9). */
export const PresentContext = createContext(false);
export const usePresent = () => useContext(PresentContext);

export type ReviewUnit = "count" | "percent" | "rkm";

export function fmt(v: number | null | undefined, unit: ReviewUnit = "count"): string {
  if (unit === "percent") return formatPercent(v, 2);
  if (unit === "rkm") return v == null ? "NA" : new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);
  return formatCount(v);
}

const TREND_CLASS: Record<string, string> = {
  better: "text-good-text",
  worse: "text-critical-text",
};

/** Change chip: arrow + absolute change, coloured by whether the change is good for this metric. */
export function Delta({ change, unit = "count", className }: { change: Pick<ReviewChange, "delta" | "trend">; unit?: ReviewUnit; className?: string }) {
  const d = change.delta;
  if (d == null) return <span className={cn("text-xs text-subtle-foreground", className)}>NA</span>;
  const Icon = d > 0 ? TrendingUp : d < 0 ? TrendingDown : Minus;
  const abs = Math.abs(d);
  const text = unit === "percent" ? `${abs.toFixed(2)} pp` : formatCount(abs);
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap text-xs font-semibold tabular", TREND_CLASS[change.trend] ?? "text-muted-foreground", className)}>
      <Icon className="size-3.5" aria-hidden />
      <span className="sr-only">{d > 0 ? "up" : d < 0 ? "down" : "no change"}</span>
      {text}
    </span>
  );
}

/** Week-on-week call-out shown under every circle table (same text as the deck). */
export function InsightBar({ items }: { items: ReviewInsight[] }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-primary/30 bg-primary-soft/50 px-4 py-3 text-sm">
      <span className="inline-flex items-center gap-1 font-semibold text-primary">
        {items[0].from} <ArrowRight className="size-3.5" aria-hidden /> {items[0].to}
      </span>
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-2">
          <span className="text-muted-foreground">{it.label}</span>
          <span className="font-semibold tabular">
            {fmt(it.previous, it.unit)} → {fmt(it.current, it.unit)}
          </span>
          <Delta change={it} unit={it.unit} />
        </span>
      ))}
    </div>
  );
}

export interface PeriodRow {
  key: string;
  label: React.ReactNode;
  values: React.ReactNode[];
  /** bold row (scope / totals) */
  strong?: boolean;
  /** muted row (NA etc.) */
  muted?: boolean;
  hint?: string;
}

/** Month / TD / week table with a sticky first column; the selected week is highlighted. */
export function PeriodTable({ periods, rows, firstHeader, caption, highlightKey }: { periods: ReviewPeriod[]; rows: PeriodRow[]; firstHeader: string; caption: string; highlightKey?: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[760px] text-[13px]">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border bg-muted/60">
            <th scope="col" className="sticky left-0 z-10 bg-muted px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {firstHeader}
            </th>
            {periods.map((p) => (
              <th
                key={p.key}
                scope="col"
                className={cn(
                  "whitespace-nowrap px-2 py-2 text-right text-[11px] font-semibold uppercase tracking-normal text-muted-foreground",
                  p.kind === "mtd" && "bg-primary-soft/60 text-primary",
                  p.key === highlightKey && "bg-primary-soft text-primary",
                )}
              >
                {p.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className={cn("border-b border-border/70 last:border-0", r.strong && "bg-muted/30 font-semibold", r.muted && "text-muted-foreground")}>
              <th scope="row" title={r.hint} className={cn("sticky left-0 z-10 whitespace-nowrap bg-card px-3 py-2 text-left font-medium", r.strong && "bg-muted")}>
                {r.label}
              </th>
              {r.values.map((v, i) => (
                <td key={periods[i]?.key ?? i} className={cn("whitespace-nowrap px-2 py-2 text-right tabular", periods[i]?.key === highlightKey && "bg-primary-soft/40")}>
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Circle drop-down used by the per-circle pages (Blocks & GPs, Block / GP network). */
export function CircleSelect({ circles, value, onChange }: { circles: { id: string; name: string; code: string }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">Circle</span>
      <Select ariaLabel="Circle" className="w-full sm:w-52" value={value} onValueChange={onChange} options={circles.map((c) => ({ value: c.id, label: `${c.name} (${c.code})` }))} />
    </div>
  );
}

/** Small bordered panel with a heading – the page's equivalent of a deck table block. */
export function Panel({ title, description, actions, children, className }: { title: string; description?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("min-w-0 space-y-3 rounded-xl border border-border bg-card p-4 sm:p-5", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold">{title}</h3>
          {description && <p className="mt-0.5 text-[13px] text-muted-foreground">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
