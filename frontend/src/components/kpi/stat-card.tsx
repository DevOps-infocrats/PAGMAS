"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { InfoTip } from "@/components/feedback/badges";
import { LoadingLabel } from "@/components/feedback/states";
import { Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";

export interface StatBreakdown {
  label: string;
  value: number | null;
  /** CSS colour of the dot / bar segment */
  color?: string;
  /** Show the share of `total` next to the value */
  showShare?: boolean;
  /** Pre-formatted value (e.g. RKM) */
  display?: string;
}

/**
 * Overview scorecard: icon, label + definition, headline value, caption and an
 * optional breakdown (with a proportion bar) for composite KPIs.
 */
export function StatCard({
  icon: Icon,
  tone,
  label,
  info,
  value,
  unit,
  caption,
  breakdown,
  bar,
  total,
  loading,
  className,
  layout = "stack",
  href,
  linkLabel = "View list",
  compact = false,
}: {
  icon: React.ComponentType<{ className?: string }>;
  /** CSS colour used for the icon tile */
  tone: string;
  label: string;
  info: React.ReactNode;
  value: string;
  unit?: string;
  caption?: React.ReactNode;
  breakdown?: StatBreakdown[];
  /** Segments of the proportion bar (subset of breakdown) */
  bar?: StatBreakdown[];
  total?: number | null;
  loading?: boolean;
  className?: string;
  /** "split": headline on the left, breakdown on the right (wide cards) */
  layout?: "stack" | "split";
  /** Makes the whole card open this page (e.g. the list behind the KPI); the info tip stays clickable */
  href?: string;
  linkLabel?: string;
  /** Shorter card (less padding and spacing, slightly smaller number) – Circle Overview */
  compact?: boolean;
}) {
  if (loading) {
    return (
      <div className={cn("rounded-xl border border-border bg-card p-5", className)} role="status" aria-label={`Loading ${label}`}>
        <div className="flex items-center justify-between">
          <Skeleton className="h-3.5 w-28" />
          <Skeleton className="size-9 rounded-lg" />
        </div>
        <Skeleton className="mt-4 h-8 w-24" />
        <Skeleton className="mt-3 h-2 w-full" />
        <LoadingLabel className="mt-3" />
      </div>
    );
  }

  const barTotal = (bar ?? []).reduce((s, b) => s + (b.value ?? 0), 0);
  const headline = (
    <div className="min-w-0">
      <div className="flex items-center gap-1.5">
        <span className="text-[13px] font-medium text-muted-foreground">{label}</span>
        <span className={cn(href && "relative z-10")}>
          <InfoTip label={label} content={info} />
        </span>
      </div>
      <p className={cn("flex items-baseline gap-1.5", compact ? "mt-1.5" : "mt-2")}>
        <span className={cn("tabular font-semibold leading-none tracking-tight", compact ? "text-[26px]" : "text-[30px]")}>{value}</span>
        {unit && <span className="text-sm font-medium text-muted-foreground">{unit}</span>}
      </p>
      {caption && <p className={cn("text-xs text-muted-foreground", compact ? "mt-1.5" : "mt-2")}>{caption}</p>}
      {href && (
        // Stretched link: the ::after layer covers the card, so a click anywhere opens the list.
        <Link
          href={href}
          aria-label={`${linkLabel}: ${label}`}
          className={cn(compact ? "mt-2" : "mt-3", "inline-flex items-center gap-1 text-xs font-semibold text-primary after:absolute after:inset-0 after:rounded-xl after:content-[''] focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring/40")}
        >
          {linkLabel} <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
        </Link>
      )}
    </div>
  );

  const details = (breakdown?.length || bar?.length) && (
    <div className={cn("min-w-0", compact ? "space-y-2" : "space-y-3")}>
      {bar && barTotal > 0 && (
        <div className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={bar.map((b) => `${b.label} ${formatCount(b.value)}`).join(", ")}>
          {bar.map((b) => (
            <span key={b.label} className="h-full first:rounded-l-full last:rounded-r-full" style={{ width: `${((b.value ?? 0) / barTotal) * 100}%`, background: b.color }} />
          ))}
        </div>
      )}
      {breakdown && (
        <dl className={cn("text-[13px]", compact ? "space-y-1" : "space-y-1.5")}>
          {breakdown.map((b) => (
            <div key={b.label} className="flex items-center justify-between gap-3">
              <dt className="flex min-w-0 items-center gap-2 text-muted-foreground">
                {b.color && <span className="size-2 shrink-0 rounded-full" style={{ background: b.color }} aria-hidden />}
                <span className="truncate">{b.label}</span>
              </dt>
              <dd className="tabular shrink-0 font-medium">
                {b.display ?? formatCount(b.value)}
                {b.showShare && total && b.value != null ? (
                  <span className="ml-1.5 text-xs font-normal text-subtle-foreground">{((b.value / total) * 100).toFixed(1)}%</span>
                ) : null}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );

  return (
    <div
      className={cn(
        "group relative flex flex-col rounded-xl border border-border bg-card transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:shadow-[0_8px_24px_-12px_rgba(15,23,42,0.18)]",
        compact ? "px-5 py-4" : "p-5",
        href && "cursor-pointer hover:border-primary/40",
        className,
      )}
    >
      <span
        className={cn("absolute right-5 flex size-9 items-center justify-center rounded-lg", compact ? "top-4" : "top-5")}
        style={{ background: `color-mix(in srgb, ${tone} 12%, transparent)`, color: tone }}
        aria-hidden
      >
        <Icon className="size-[18px]" />
      </span>
      {layout === "split" && details ? (
        <div className={cn("grid flex-1 grid-cols-1 pr-12", compact ? "gap-4" : "gap-5", "sm:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] sm:items-center")}>
          {headline}
          {details}
        </div>
      ) : (
        <div className={cn("flex flex-1 flex-col pr-12", compact ? "gap-3" : "gap-4")}>
          {headline}
          {details && <div className="-mr-12 mt-auto">{details}</div>}
        </div>
      )}
    </div>
  );
}
