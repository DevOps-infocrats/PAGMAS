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
  dense = false,
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
  /** Further reduces vertical spacing for single-row summary cards. */
  dense?: boolean;
}) {
  if (loading) {
    return (
      <div className={cn("rounded-xl border border-border bg-card px-4 shadow-sm", dense ? "py-2" : "py-3", className)} role="status" aria-label={`Loading ${label}`}>
        <div className="flex items-center justify-between">
          <Skeleton className="h-3.5 w-28" />
          <Skeleton className="size-6 rounded-md" />
        </div>
        <Skeleton className="mt-2.5 h-6 w-24" />
        <Skeleton className="mt-2 h-2 w-full" />
        <LoadingLabel className="mt-2" />
      </div>
    );
  }

  const barTotal = (bar ?? []).reduce((s, b) => s + (b.value ?? 0), 0);
  const headline = (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <span
          className="flex size-6 shrink-0 items-center justify-center rounded-md"
          style={{ background: `color-mix(in srgb, ${tone} 14%, transparent)`, color: tone }}
          aria-hidden
        >
          <Icon className="size-3.5" />
        </span>
        <span className="text-[13px] font-bold text-subheading">{label}</span>
        <span className={cn(href && "relative z-10")}>
          <InfoTip label={label} content={info} />
        </span>
      </div>
      <p className={cn("flex items-baseline gap-1.5", dense ? "mt-1" : "mt-1.5")}>
        <span className={cn("tabular font-bold leading-none tracking-tight text-heading", dense ? "text-[22px]" : compact ? "text-[24px]" : "text-[26px]")}>{value}</span>
        {unit && <span className="text-[13px] font-medium text-muted-foreground">{unit}</span>}
      </p>
      {caption && <p className={cn("text-xs text-muted-foreground", dense ? "mt-0.5" : "mt-1")}>{caption}</p>}
      {href && (
        // Stretched link: the ::after layer covers the card, so a click anywhere opens the list.
        <Link
          href={href}
          aria-label={`${linkLabel}: ${label}`}
          className={cn(dense ? "mt-1" : "mt-1.5", "inline-flex items-center gap-1 text-xs font-semibold text-primary after:absolute after:inset-0 after:rounded-xl after:content-[''] focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring/40")}
        >
          {linkLabel} <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
        </Link>
      )}
    </div>
  );

  const details = (breakdown?.length || bar?.length) && (
    <div className={cn("min-w-0", dense ? "space-y-1.5" : "space-y-2")}>
      {bar && barTotal > 0 && (
        <div className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={bar.map((b) => `${b.label} ${formatCount(b.value)}`).join(", ")}>
          {bar.map((b) => (
            <span key={b.label} className="h-full first:rounded-l-full last:rounded-r-full" style={{ width: `${((b.value ?? 0) / barTotal) * 100}%`, background: b.color }} />
          ))}
        </div>
      )}
      {breakdown && (
        <dl className={cn("text-[13px]", dense ? "space-y-0.5" : "space-y-1")}>
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
        "group relative flex flex-col overflow-hidden rounded-xl border border-border bg-card shadow-sm transition-[box-shadow,transform,border-color] duration-200",
        "px-4",
        dense ? "py-2" : compact ? "py-3" : "py-3.5",
        href && "cursor-pointer hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md",
        className,
      )}
    >
      <span className="absolute inset-x-0 top-0 h-[3px]" style={{ background: tone }} aria-hidden />
      {layout === "split" && details ? (
        <div className="grid flex-1 grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] sm:items-center">
          {headline}
          {details}
        </div>
      ) : (
        <div className={cn("flex flex-1 flex-col", dense ? "gap-2" : "gap-2.5")}>
          {headline}
          {details && <div className="mt-auto">{details}</div>}
        </div>
      )}
    </div>
  );
}
