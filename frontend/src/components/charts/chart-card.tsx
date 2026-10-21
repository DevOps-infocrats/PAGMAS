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
    <Card className={cn("flex min-w-0 flex-col", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4 sm:flex-nowrap">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h3 className="text-[15px] font-semibold">{title}</h3>
            {info && <InfoTip label={title} content={info} />}
          </div>
          {(description || period) && (
            <p className="mt-0.5 text-[13px] text-muted-foreground">
              {description}
              {description && period && " · "}
              {period && <span className="text-subtle-foreground">{period}</span>}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {actions}
          {table && (
            <div className="inline-flex rounded-md border border-border p-0.5" role="group" aria-label={`${title} view`}>
              <button
                type="button"
                aria-pressed={view === "chart"}
                aria-label="Chart view"
                onClick={() => setView("chart")}
                className={cn("rounded p-1 text-muted-foreground hover:text-foreground", view === "chart" && "bg-muted text-foreground")}
              >
                <BarChart3 className="size-4" />
              </button>
              <button
                type="button"
                aria-pressed={view === "table"}
                aria-label="Table view"
                onClick={() => setView("table")}
                className={cn("rounded p-1 text-muted-foreground hover:text-foreground", view === "table" && "bg-muted text-foreground")}
              >
                <Table2 className="size-4" />
              </button>
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
      <thead className="sticky top-0 bg-card">
        <tr className="border-b border-border text-left text-muted-foreground">
          {columns.map((c, i) => (
            <th key={c} scope="col" className={cn("px-2 py-2 font-medium", i > 0 && "text-right")}>
              {c}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, ri) => (
          <tr key={ri} className="border-b border-border/60 last:border-0">
            {r.map((cell, ci) => (
              <td key={ci} className={cn("px-2 py-1.5", ci > 0 && "tabular text-right")}>
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
