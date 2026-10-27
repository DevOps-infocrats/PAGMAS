"use client";

import { BarChart3, Table2 } from "lucide-react";
import { useState } from "react";
import { ChartSkeleton, EmptyState, ErrorState } from "@/components/feedback/states";
import { InfoTip } from "@/components/feedback/badges";
import { Card } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";

/**
 * Card shell for every chart: title, description, period label, actions,
 * loading/empty/error states and an accessible table-view toggle.
 */
export function ChartCard({
  title,
  description,
  info,
  period,
  actions,
  loading,
  error,
  onRetry,
  empty,
  emptyMessage = "No records match the current selection.",
  height = 280,
  table,
  children,
  className,
}: {
  title: string;
  description?: string;
  info?: string;
  period?: string;
  actions?: React.ReactNode;
  loading?: boolean;
  error?: Error;
  onRetry?: () => void;
  empty?: boolean;
  emptyMessage?: string;
  height?: number;
  /** Optional tabular view of the same data (accessibility + exact values). */
  table?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  const [view, setView] = useState<"chart" | "table">("chart");
  return (
    <Card className={cn("flex min-w-0 flex-col overflow-hidden transition-shadow duration-200 hover:shadow-md", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border bg-gradient-to-r from-primary-soft/70 via-card to-card px-5 py-3 sm:flex-nowrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="brand-gradient-v h-[18px] w-1 shrink-0 rounded-full" aria-hidden />
            <h3 className="text-[15.5px] font-bold text-subheading">{title}</h3>
            {info && <InfoTip label={title} content={info} />}
          </div>
          {(description || period) && (
            <p className="mt-0.5 pl-3 text-[13px] leading-relaxed text-subheading/70">
              {description}
              {description && period && " · "}
              {period && <span className="text-subtle-foreground">{period}</span>}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          {table && (
            <div className="inline-flex items-center overflow-hidden rounded-md border border-input" role="group" aria-label={`${title} view`}>
              {(
                [
                  ["chart", "Chart", BarChart3],
                  ["table", "Table", Table2],
                ] as const
              ).map(([v, label, Icon]) => (
                <button
                  key={v}
                  type="button"
                  aria-pressed={view === v}
                  onClick={() => setView(v)}
                  className={cn(
                    "inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors last:border-l last:border-input hover:bg-accent hover:text-foreground",
                    view === v && "bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground",
                  )}
                >
                  <Icon className="size-3.5" aria-hidden />
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="min-w-0 flex-1 px-3 pb-3 pt-3 sm:px-4">
        {error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : loading ? (
          <ChartSkeleton height={height} />
        ) : empty ? (
          <EmptyState title="Nothing to show" description={emptyMessage} />
        ) : view === "table" && table ? (
          <div className="overflow-auto px-1" style={{ maxHeight: height + 40 }}>
            {table}
          </div>
        ) : (
          children
        )}
      </div>
    </Card>
  );
}

/** Small accessible table used as the "table view" of a chart. */
export function MiniTable({ columns, rows }: { columns: string[]; rows: (string | number)[][] }) {
  return (
    <table className="w-full text-[13px]">
      <thead className="sticky top-0 bg-table-head">
        <tr className="border-b border-border text-left text-heading">
          {columns.map((c, i) => (
            <th key={c} scope="col" className={cn("px-2.5 py-2 text-[12.5px] font-semibold", i > 0 && "text-right")}>
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, ri) => (
          <tr key={ri} className="border-b border-border/60 last:border-0 even:bg-muted/45 hover:bg-accent">
            {r.map((cell, ci) => (
              <td key={ci} className={cn("px-2.5 py-2", ci > 0 && "tabular text-right", ci === 0 && "font-medium")}>
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
