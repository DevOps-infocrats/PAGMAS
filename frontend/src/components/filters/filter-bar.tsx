"use client";

import { CalendarDays } from "lucide-react";
import { useMeta } from "@/components/providers/data-provider";
import { Select } from "@/components/ui/overlays";
import { useFilters } from "@/hooks/use-filters";
import { cn } from "@/lib/utils/cn";
import { formatShortDate } from "@/lib/utils/format";
import { SearchableSelect } from "./searchable-select";

/** Horizontal filter row shown above page content (single row, wraps on mobile). */
export function FilterBar({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-3 rounded-lg border border-border bg-card p-3 sm:flex-row sm:flex-wrap sm:items-end", className)}>
      {children}
    </div>
  );
}

export function CircleFilter({ required, className, hideLabel }: { required?: boolean; className?: string; hideLabel?: boolean }) {
  const meta = useMeta();
  const { filters, setFilters } = useFilters();
  return (
    <SearchableSelect
      label="Circle / State"
      hideLabel={hideLabel}
      className={cn("sm:w-56", className)}
      value={filters.circle}
      disabled={!meta}
      allowClear={!required}
      clearLabel="All circles"
      placeholder="Select a circle"
      options={(meta?.circles ?? []).map((c) => ({ value: c.id, label: c.name, hint: c.code }))}
      onChange={(v) => setFilters({ circle: v })}
    />
  );
}

export function DistrictFilter({ required, className, hideLabel }: { required?: boolean; className?: string; hideLabel?: boolean }) {
  const meta = useMeta();
  const { filters, setFilters } = useFilters();
  const options = (meta?.districts ?? []).filter((d) => d.circleId === filters.circle).map((d) => ({ value: d.id, label: d.name }));
  return (
    <SearchableSelect
      label="District"
      hideLabel={hideLabel}
      className={cn("sm:w-52", className)}
      value={filters.district}
      disabled={!meta || !filters.circle}
      allowClear={!required}
      clearLabel="All districts"
      placeholder={filters.circle ? "Select a district" : "Select a circle first"}
      options={options}
      onChange={(v) => setFilters({ district: v })}
    />
  );
}

/** `allDistricts`: list every block of the circle even when a district is in the URL (pages without a district filter). */
export function BlockFilter({ required, className, allDistricts, hideLabel }: { required?: boolean; className?: string; allDistricts?: boolean; hideLabel?: boolean }) {
  const meta = useMeta();
  const { filters, setFilters } = useFilters();
  const options = (meta?.blocks ?? [])
    .filter((b) => b.circleId === filters.circle && (allDistricts || !filters.district || b.districtId === filters.district))
    .map((b) => ({ value: b.id, label: b.name, hint: b.code }));
  return (
    <SearchableSelect
      label="Block"
      hideLabel={hideLabel}
      className={cn("sm:w-56", className)}
      value={filters.block}
      disabled={!meta || !filters.circle}
      allowClear={!required}
      clearLabel="All blocks"
      placeholder={filters.circle ? "Select a block" : "Select a circle first"}
      options={options}
      onChange={(v) => {
        const b = meta?.blocks.find((x) => x.id === v);
        setFilters(b ? { district: b.districtId, block: v } : { block: v });
      }}
    />
  );
}

/** Reporting week + comparison week selectors. */
export function PeriodFilter({
  showWeek = true,
  showCompare = true,
  className,
  fill,
}: {
  showWeek?: boolean;
  showCompare?: boolean;
  className?: string;
  /** Selects fill their grid column (title-bar grids) instead of a fixed width */
  fill?: boolean;
}) {
  const meta = useMeta();
  const { period, setFilters } = useFilters();
  const weeks = [...(meta?.weeks ?? [])].reverse();
  const opts = weeks.map((w) => ({ value: w.id, label: `${w.label} · ${formatShortDate(w.startDate)}–${formatShortDate(w.endDate)}` }));
  return (
    <div className={cn("flex flex-col gap-3 sm:flex-row sm:items-end", fill && "w-full", className)}>
      {showWeek && (
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
          <CalendarDays className="size-3.5" /> Reporting week
        </span>
        <Select
          ariaLabel="Reporting week"
          className="w-full sm:w-60"
          value={period?.weekId}
          disabled={!meta}
          options={opts}
          onValueChange={(v) => {
            const idx = weeks.findIndex((w) => w.id === v);
            const prev = weeks[idx + 1]?.id ?? v;
            setFilters({ week: v, compare: prev });
          }}
        />
      </div>
      )}
      {showCompare && (
        <div className={cn("flex flex-col gap-1", fill && "w-full")}>
          <span className="text-xs font-medium text-muted-foreground">Compare with</span>
          <Select
            ariaLabel="Comparison week"
            className={cn("w-full", fill ? "min-w-0 whitespace-nowrap [&>span]:truncate" : "sm:w-60")}
            value={period?.compareWeekId}
            disabled={!meta}
            options={opts.filter((o) => o.value !== period?.weekId)}
            onValueChange={(v) => setFilters({ compare: v })}
          />
        </div>
      )}
    </div>
  );
}
