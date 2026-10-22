"use client";

import { useSearchParams } from "next/navigation";
import { CircleFilter } from "@/components/filters/filter-bar";
import { Breadcrumbs } from "@/components/layout/page-header";
import { useMeta } from "@/components/providers/data-provider";
import { useFilters } from "@/hooks/use-filters";
import { AMC_PATH, AMC_VIEWS, amcViewFrom } from "@/lib/amc-views";
import { AmcPlanSummaryView } from "./amc-plan-summary";
import { AmcPlanTimelineView } from "./amc-plan-timeline";

/**
 * AMC Conversion – Plan vs Execution, one view at a time (?view=, sidebar sub-menu):
 *  summary / monthly / weekly – GP-wise plan of the master data file (Planned Date = target, Ach Date = achieved)
 */
export function AmcConversionView() {
  const params = useSearchParams();
  const meta = useMeta();
  const { filters, hrefTo } = useFilters();
  const view = AMC_VIEWS.find((v) => v.id === amcViewFrom(params.get("view")))!;
  const stateName = meta?.circles.find((c) => c.id === filters.circle)?.name;
  const pageHref = (() => {
    const base = hrefTo(AMC_PATH, { circle: undefined, district: undefined, block: undefined, gp: undefined });
    return `${base}${base.includes("?") ? "&" : "?"}view=${view.id}`;
  })();
  return (
    <div className="space-y-5">
      {/* ---------------- Title bar: same in every view, like the other pages ---------------- */}
      <header className="rounded-xl border border-border bg-card shadow-sm">
        <div className="space-y-0.5 px-4 py-2.5">
          <Breadcrumbs
            items={[
              { label: "Circle Overview", href: hrefTo("/dashboard", { circle: undefined, district: undefined, block: undefined, gp: undefined }) },
              stateName ? { label: "AMC Conversion Plan vs Execution", href: pageHref } : { label: "AMC Conversion Plan vs Execution" },
              ...(stateName ? [{ label: stateName }] : []),
            ]}
          />
          <h1 className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-lg font-semibold leading-tight">
            {stateName ?? "AMC Conversion Plan vs Execution"}
            <span className="text-subtle-foreground" aria-hidden>
              ·
            </span>
            <span className="text-primary">{view.title}</span>
            <span className="text-[13px] font-semibold text-foreground">{stateName ? "AMC conversion plan vs execution of this state." : "All states – select a state to see only its figures."}</span>
          </h1>
        </div>
        {/* State (shared filter); the view is kept */}
        <div className="grid grid-cols-1 gap-x-4 gap-y-2 border-t border-border px-4 py-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <CircleFilter className="sm:w-full" />
        </div>
      </header>
      {view.id === "summary" && <AmcPlanSummaryView />}
      {(view.id === "monthly" || view.id === "weekly") && <AmcPlanTimelineView key={view.id} view={view.id} />}
    </div>
  );
}
