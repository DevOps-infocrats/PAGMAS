"use client";

import {
  columnFilteringFeature,
  createColumnHelper,
  createFilteredRowModel,
  createPaginatedRowModel,
  createSortedRowModel,
  filterFn_includesString,
  globalFilteringFeature,
  rowPaginationFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  sortFn_text,
  tableFeatures,
  useTable,
  type ColumnDef,
  type PaginationState,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Download, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/primitives";
import { Select } from "@/components/ui/overlays";
import { IS_LIVE } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";

export const tableFeats = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFn_alphanumeric, text: sortFn_text, basic: sortFn_basic },
  columnFilteringFeature,
  globalFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { includesString: filterFn_includesString },
  rowPaginationFeature,
  paginatedRowModel: createPaginatedRowModel(),
});

export type TableFeats = typeof tableFeats;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Column<T extends RowData> = ColumnDef<TableFeats, T, any>;
export const columnHelper = <T extends RowData>() => createColumnHelper<TableFeats, T>();

const EMPTY: never[] = [];

/**
 * Searchable, sortable, paginated table. Client-side today; the same props can
 * drive server pagination later (manual mode) without changing call sites.
 */
export function DataTable<T extends RowData>({
  data,
  columns,
  loading,
  error,
  onRetry,
  searchPlaceholder = "Search…",
  onRowClick,
  rowLabel,
  numericColumns = [],
  initialSort,
  pageSize: initialPageSize = 10,
  toolbar,
  exportName,
  emptyMessage = "No records match the current search.",
}: {
  data: T[] | undefined;
  columns: Column<T>[];
  loading?: boolean;
  error?: Error;
  onRetry?: () => void;
  searchPlaceholder?: string;
  onRowClick?: (row: T) => void;
  /** Accessible label for row activation, e.g. (row) => `Open ${row.name}` */
  rowLabel?: (row: T) => string;
  numericColumns?: string[];
  initialSort?: SortingState;
  pageSize?: number;
  toolbar?: React.ReactNode;
  /** When set, shows a CSV export of the filtered rows (demo data is labelled). */
  exportName?: string;
  emptyMessage?: string;
}) {
  const [sorting, setSorting] = useState<SortingState>(initialSort ?? []);
  const [globalFilter, setGlobalFilter] = useState("");
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: initialPageSize });

  const table = useTable({
    features: tableFeats,
    columns,
    data: data ?? (EMPTY as T[]),
    state: { sorting, globalFilter, pagination },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onPaginationChange: setPagination,
    globalFilterFn: "includesString",
  });

  const numeric = useMemo(() => new Set(numericColumns), [numericColumns]);
  const filteredCount = table.getFilteredRowModel().rows.length;
  const pageCount = table.getPageCount();

  const exportCsv = () => {
    const rows = table.getFilteredRowModel().rows;
    const headers = table.getAllLeafColumns().map((c) => c.id);
    const esc = (v: unknown) => `"${String(v ?? "NA").replace(/"/g, '""')}"`;
    const csv = [
      ...(IS_LIVE ? [] : ["# DEMO DATA - generated for UI development, not company data"]),
      headers.join(","),
      ...rows.map((r) => headers.map((h) => esc(r.getValue(h))).join(",")),
    ].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${exportName}${IS_LIVE ? "" : "_DEMO"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col">
      <div className="flex flex-col gap-3 border-b border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-xs">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" />
          <Input
            value={globalFilter}
            onChange={(e) => {
              setGlobalFilter(e.target.value);
              setPagination((p) => ({ ...p, pageIndex: 0 }));
            }}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="pl-9"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {toolbar}
          {exportName && (
            <Button size="sm" variant="outline" onClick={exportCsv} disabled={!data?.length}>
              <Download /> Export CSV
            </Button>
          )}
        </div>
      </div>

      {error ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : loading || !data ? (
        <TableSkeleton />
      ) : filteredCount === 0 ? (
        <EmptyState title="No results" description={data.length ? emptyMessage : "There are no records for this selection."} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-border bg-muted/50">
                  {hg.headers.map((header) => {
                    const sorted = header.column.getIsSorted();
                    const canSort = header.column.getCanSort();
                    const isNum = numeric.has(header.column.id);
                    return (
                      <th
                        key={header.id}
                        scope="col"
                        aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                        className={cn("whitespace-nowrap px-4 py-2.5 text-xs font-medium text-muted-foreground", isNum ? "text-right" : "text-left")}
                      >
                        {header.isPlaceholder ? null : canSort ? (
                          <button
                            type="button"
                            onClick={header.column.getToggleSortingHandler()}
                            className={cn("inline-flex items-center gap-1 rounded hover:text-foreground", isNum && "flex-row-reverse")}
                          >
                            <table.FlexRender header={header} />
                            {sorted === "asc" ? (
                              <ArrowUp className="size-3.5" />
                            ) : sorted === "desc" ? (
                              <ArrowDown className="size-3.5" />
                            ) : (
                              <ArrowUpDown className="size-3.5 opacity-40" />
                            )}
                          </button>
                        ) : (
                          <table.FlexRender header={header} />
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  tabIndex={onRowClick ? 0 : undefined}
                  aria-label={onRowClick && rowLabel ? rowLabel(row.original) : undefined}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                  onKeyDown={
                    onRowClick
                      ? (e) => {
                          if (e.key === "Enter" && e.target === e.currentTarget) onRowClick(row.original);
                        }
                      : undefined
                  }
                  className={cn("border-b border-border/70 last:border-0", onRowClick && "cursor-pointer hover:bg-accent/60 focus-visible:bg-accent")}
                >
                  {row.getAllCells().map((cell) => (
                    <td key={cell.id} className={cn("whitespace-nowrap px-4 py-2.5", numeric.has(cell.column.id) && "tabular text-right")}>
                      <table.FlexRender cell={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && filteredCount > 0 && (
        <div className="flex flex-col gap-3 border-t border-border px-4 py-3 text-[13px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <span>
            {formatCount(pagination.pageIndex * pagination.pageSize + 1)}–
            {formatCount(Math.min(filteredCount, (pagination.pageIndex + 1) * pagination.pageSize))} of {formatCount(filteredCount)}
            {filteredCount !== data.length && ` (filtered from ${formatCount(data.length)})`}
          </span>
          <div className="flex items-center gap-2">
            <span className="hidden sm:inline">Rows</span>
            <Select
              ariaLabel="Rows per page"
              value={String(pagination.pageSize)}
              onValueChange={(v) => setPagination({ pageIndex: 0, pageSize: Number(v) })}
              options={["10", "25", "50", "100"].map((v) => ({ value: v, label: v }))}
              className="h-8 w-[72px]"
            />
            <Button size="icon-sm" variant="outline" aria-label="Previous page" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}>
              <ChevronLeft />
            </Button>
            <span className="tabular min-w-16 text-center">
              {pagination.pageIndex + 1} / {Math.max(1, pageCount)}
            </span>
            <Button size="icon-sm" variant="outline" aria-label="Next page" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}>
              <ChevronRight />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
