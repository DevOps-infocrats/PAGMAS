"use client";

import { useSearchParams } from "next/navigation";
import { CircleFilter } from "@/components/filters/filter-bar";
import { TitleBar, ViewHint } from "@/components/layout/page-header";
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
  const planPage = view.id === "monthly" || view.id === "weekly";
  return (
    <div className={planPage ? "space-y-3" : "space-y-5"}>
      {/* ---------------- Title bar: same in every view, like the other pages ---------------- */}
      <TitleBar
        breadcrumbs={[
          { label: "Circle Overview", href: hrefTo("/dashboard", { circle: undefined, district: undefined, block: undefined, gp: undefined }) },
          stateName ? { label: "AMC Conversion Plan vs Execution", href: pageHref } : { label: "AMC Conversion Plan vs Execution" },
          ...(stateName ? [{ label: stateName }] : []),
        ]}
        title={stateName ?? "AMC Conversion Plan vs Execution"}
        view={view.title}
        note={stateName ? "AMC conversion plan vs execution of this state." : "All states – select a state to see only its figures."}
        compact={planPage}
      >
        {/* State (shared filter); the view is kept */}
        <CircleFilter className="sm:w-full" />
      </TitleBar>
      <div key={view.id} className={planPage ? "view-in space-y-3" : "view-in space-y-5"}>
        <ViewHint>{view.hint}</ViewHint>
        {view.id === "summary" && <AmcPlanSummaryView />}
        {(view.id === "monthly" || view.id === "weekly") && <AmcPlanTimelineView key={view.id} view={view.id} />}
      </div>
    </div>
  );
}
