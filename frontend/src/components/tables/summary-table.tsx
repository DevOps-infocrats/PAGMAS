import { cn } from "@/lib/utils/cn";

export interface SummaryColumn<T> {
  key: string;
  header: string;
  /** Right-aligned numeric column */
  numeric?: boolean;
  render: (row: T) => React.ReactNode;
}

/**
 * Compact report-style table shown under a chart: header, rows, optional
 * total row. Rows can be activated with click or Enter.
 */
export function SummaryTable<T>({
  columns,
  rows,
  total,
  rowKey,
  onRowClick,
  rowLabel,
  caption,
}: {
  columns: SummaryColumn<T>[];
  rows: T[];
  total?: Record<string, React.ReactNode>;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  rowLabel?: (row: T) => string;
  caption?: string;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[560px] text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-border bg-muted/60">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={cn("whitespace-nowrap px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground", c.numeric ? "text-right" : "text-left")}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={rowKey(r)}
              tabIndex={onRowClick ? 0 : undefined}
              aria-label={onRowClick && rowLabel ? rowLabel(r) : undefined}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              onKeyDown={onRowClick ? (e) => e.key === "Enter" && e.target === e.currentTarget && onRowClick(r) : undefined}
              className={cn("border-b border-border/70 last:border-0", onRowClick && "cursor-pointer hover:bg-accent/60 focus-visible:bg-accent")}
            >
              {columns.map((c, i) => (
                <td key={c.key} className={cn("whitespace-nowrap px-4 py-2.5", c.numeric && "tabular text-right", i === 0 && "font-medium")}>
                  {c.render(r)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {total && (
          <tfoot>
            <tr className="border-t border-border bg-muted/40 font-semibold">
              {columns.map((c) => (
                <td key={c.key} className={cn("whitespace-nowrap px-4 py-2.5", c.numeric && "tabular text-right")}>
                  {total[c.key] ?? ""}
                </td>
              ))}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
