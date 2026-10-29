"use client";

import { Card } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";
import { formatPercent } from "@/lib/utils/format";

/* Table look shared by the AMC Conversion views – the same as the dashboard's other tables (SummaryTable / PeriodGrid):
   light grey header with small upper-case labels, right-aligned numbers, sticky first column, grey total row,
   current period tinted. */

/** Card with the same header as the chart cards (title, description, actions on the right). */
export function TableCard({ title, description, actions, children }: { title: string; description?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Card className="flex min-w-0 flex-col">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border/70 px-5 py-3.5 sm:flex-nowrap">
        <div className="min-w-0 flex-1">
          <h3 className="text-[15px] font-bold text-subheading">{title}</h3>
          {description && <p className="mt-0.5 text-[13px] leading-relaxed text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="min-w-0 px-3 pb-3 pt-3 sm:px-4">{children}</div>
    </Card>
  );
}

/** Header cell: small upper-case grey label; numbers right-aligned; `group` starts a column group (left rule). */
export function Th({
  children,
  first,
  center,
  group,
  current,
  className,
  ...rest
}: React.ComponentProps<"th"> & { first?: boolean; center?: boolean; group?: boolean; current?: boolean }) {
  return (
    <th
      scope="col"
      className={cn(
        "whitespace-nowrap px-2.5 py-2.5 text-[12.5px] font-semibold text-foreground",
        first ? "sticky left-0 z-10 bg-muted px-3 text-left" : center ? "text-center" : "text-right",
        group && "border-l border-border/70",
        current && "text-primary",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

/** Body / total cell: numbers right-aligned; the current period is tinted. */
export function Td({ children, group, current, className }: { children: React.ReactNode; group?: boolean; current?: boolean; className?: string }) {
  return <td className={cn("whitespace-nowrap px-2.5 py-2.5 text-right", group && "border-l border-border/70", current && "bg-primary-soft/40", className)}>{children}</td>;
}

/** Row label (first column) of a body row or of the total row. */
export function RowHead({ children, total, className }: { children: React.ReactNode; total?: boolean; className?: string }) {
  return (
    <th scope="row" className={cn("sticky left-0 z-10 whitespace-nowrap px-3 py-2.5 text-left", total ? "bg-muted font-semibold" : "bg-card font-medium", className)}>
      {children}
    </th>
  );
}

export const HEAD_ROW = "border-b border-border bg-muted";

/** Bordered grid for the AMC Plan vs Execution tables (opt-in): outer frame, a rule around every cell, bold header with a
 *  heavier bottom rule, slightly shorter rows. Scoped to the table it is put on – other tables keep their look. */
export const GRID_WRAP = "overflow-x-auto rounded-lg border border-subtle-foreground/30 bg-card shadow-xs";
export const GRID_TABLE = cn(
  "border-collapse",
  "[&_td]:border [&_th]:border [&_td]:border-border/80 [&_th]:border-border",
  "[&_td]:py-2 [&_th]:py-2",
  "[&_thead_th]:font-bold [&_thead_th]:text-subheading",
  "[&_thead_tr:last-child_th]:border-b-2 [&_thead_tr:last-child_th]:border-b-subtle-foreground/30",
  "[&_tr>*:first-child]:border-l-0 [&_tr>*:last-child]:border-r-0 [&_thead_tr:first-child>*]:border-t-0",
);
export const BODY_ROW = "border-b border-border/70 last:border-0 transition-colors hover:bg-accent/60";
export const TOTAL_ROW = "border-t border-border bg-muted/50 font-semibold";

/** Achieved share of a target as coloured text: green at 100%+, amber from 75%, red below; — when not started. */
export function PctValue({ pct, started = true }: { pct: number | null | undefined; started?: boolean }) {
  if (pct == null || !started) return <span className="text-muted-foreground">—</span>;
  const tone = pct >= 100 ? "text-good-text" : pct >= 75 ? "text-warning-text" : "text-critical-text";
  return <span className={cn("font-medium", tone)}>{formatPercent(pct, 1)}</span>;
}
