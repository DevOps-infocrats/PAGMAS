"use client";

import Link from "next/link";
import { InfoTip } from "@/components/feedback/badges";
import { Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";

/**
 * Small KPI tile (ticket pages): coloured top line, icon, label + definition, value and a one-line caption. Less
 * height and width than StatCard so a row of 3–5 fits on one line. `href` / `onClick` make the whole tile clickable;
 * `active` marks the tile whose list is shown.
 */
export function MiniKpi({
  icon: Icon,
  tone,
  label,
  info,
  value,
  unit,
  caption,
  loading,
  href,
  onClick,
  active,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>;
  tone: string;
  label: string;
  info: React.ReactNode;
  value: string;
  unit?: string;
  caption?: React.ReactNode;
  loading?: boolean;
  href?: string;
  onClick?: () => void;
  active?: boolean;
  className?: string;
}) {
  if (loading)
    return (
      <div className={cn("rounded-lg border border-border bg-card px-3 py-2 shadow-xs", className)} role="status" aria-label={`Loading ${label}`}>
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-2 h-5 w-14" />
      </div>
    );
  const clickable = !!(href || onClick);
  const stretch = "after:absolute after:inset-0 after:rounded-lg after:content-[''] focus-visible:outline-none focus-visible:after:ring-2 focus-visible:after:ring-ring/40";
  return (
    <div
      className={cn(
        "group relative min-w-0 overflow-hidden rounded-lg border border-border bg-card px-3 pb-2 pt-2.5 shadow-xs transition-[box-shadow,border-color]",
        clickable && "cursor-pointer hover:border-primary/40 hover:shadow-sm",
        className,
      )}
      style={active ? { boxShadow: `0 0 0 2px color-mix(in srgb, ${tone} 55%, transparent)`, borderColor: tone } : undefined}
    >
      <span className="absolute inset-x-0 top-0 h-[0.1875rem]" style={{ background: tone }} aria-hidden />
      <div className="flex items-center gap-1.5">
        <span className="flex size-5 shrink-0 items-center justify-center rounded" style={{ background: `color-mix(in srgb, ${tone} 14%, transparent)`, color: tone }} aria-hidden>
          <Icon className="size-3" />
        </span>
        {href ? (
          <Link href={href} className={cn("min-w-0 truncate text-[0.75rem] font-bold text-subheading", stretch)} title={label}>
            {label}
          </Link>
        ) : onClick ? (
          <button type="button" onClick={onClick} aria-pressed={active} className={cn("min-w-0 truncate text-left text-[0.75rem] font-bold text-subheading", stretch)} title={label}>
            {label}
          </button>
        ) : (
          <span className="min-w-0 truncate text-[0.75rem] font-bold text-subheading" title={label}>
            {label}
          </span>
        )}
        <span className={cn("ml-auto shrink-0", clickable && "relative z-10")}>
          <InfoTip label={label} content={info} />
        </span>
      </div>
      <p className="mt-1 flex items-baseline gap-1">
        <span className="tabular text-[1.1875rem] font-bold leading-none text-heading">{value}</span>
        {unit && <span className="text-[0.71875rem] font-medium text-muted-foreground">{unit}</span>}
      </p>
      {caption && <p className="mt-0.5 truncate text-[0.6875rem] text-muted-foreground">{caption}</p>}
    </div>
  );
}
