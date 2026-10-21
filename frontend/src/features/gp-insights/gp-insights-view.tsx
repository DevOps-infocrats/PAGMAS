"use client";

import { ArrowRight, MapPin } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { LifecycleBadge } from "@/components/feedback/badges";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { BlockFilter, CircleFilter, DistrictFilter } from "@/components/filters/filter-bar";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { Breadcrumbs } from "@/components/layout/page-header";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useDefaultSelection } from "@/hooks/use-default-selection";
import { useFilters } from "@/hooks/use-filters";
import { api, type GpDetailResponse } from "@/lib/api";
import { GP_PATH, GP_VIEWS, gpViewFrom, type GpViewId } from "@/lib/gp-views";
import { formatDate } from "@/lib/utils/format";
import { GpKpis } from "./gp-kpis";
import { GpUptimeSection } from "./gp-uptime";

/**
 * GP Insights: a title bar (breadcrumb, GP + view name, state / district / block / GP pickers) and ONE view
 * at a time, chosen from the sidebar sub-menu (?view=). Changing any picker keeps the view; Back returns to
 * the same view.
 */
export function GpInsightsView() {
  const params = useSearchParams();
  const { filters, period, setFilters, hrefTo } = useFilters();
  useDefaultSelection("block");
  const gpList = useApiQuery(filters.block && period ? `gplist:${filters.block}:${period.weekId}` : null, () => api.listGps({ blockId: filters.block, weekId: period!.weekId, pageSize: 1000 }));
  const q = useApiQuery(filters.gp && period ? `gp:${filters.gp}:${period.weekId}` : null, () => api.getGpDetail(filters.gp!, period!.weekId));
  const d = q.data;

  const viewId = gpViewFrom(params.get("view"));
  const view = GP_VIEWS.find((v) => v.id === viewId)!;
  const viewHref = (id: string) => {
    const base = hrefTo(GP_PATH);
    return `${base}${base.includes("?") ? "&" : "?"}view=${id}`;
  };

  return (
    <div className="space-y-5">
      {/* ---------------- Title bar: same in every view (scrolls with the page) ---------------- */}
      <header className="rounded-xl border border-border bg-card shadow-sm">
        <div className="space-y-0.5 px-4 py-2.5">
          <Breadcrumbs
            items={[
              { label: "Circle Overview", href: hrefTo("/dashboard") },
              ...(d
                ? [
                    { label: d.gp.circleName, href: hrefTo("/dashboard/circle-insights", { district: undefined, block: undefined, gp: undefined }) },
                    { label: d.gp.districtName },
                    { label: d.gp.blockName, href: hrefTo("/dashboard/block-insights", { gp: undefined }) },
                    { label: d.gp.name },
                  ]
                : [{ label: "GP Insights" }]),
            ]}
          />
          {/* title and its context on one line ("data as of" is already in the top header) */}
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <h1 className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-lg font-semibold leading-tight">
              {d ? d.gp.name : "GP Insights"}
              <span className="text-subtle-foreground" aria-hidden>
                ·
              </span>
              <span className="text-primary">{view.title}</span>
              <span className="text-[13px] font-normal text-muted-foreground">
                {d && period
                  ? `LGD ${d.gp.lgdCode} · ID ${d.gp.id.toUpperCase()} · ${period.week.label} (${formatDate(period.week.startDate)} – ${formatDate(period.week.endDate)})`
                  : "Select a Gram Panchayat to see its details."}
              </span>
            </h1>
            {d && <LifecycleBadge status={d.gp.lifecycle} />}
          </div>
        </div>
        {/* All pickers change this page; the view is kept */}
        {/* four equal columns: every control lines up and none is squeezed */}
        <div className="grid grid-cols-1 gap-x-4 gap-y-2 border-t border-border px-4 py-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <CircleFilter required className="sm:w-full" />
          <DistrictFilter className="sm:w-full" />
          <BlockFilter required className="sm:w-full" />
          <SearchableSelect
            label="Gram Panchayat"
            className="w-full"
            value={filters.gp}
            disabled={!gpList.data}
            placeholder={gpList.loading ? "Loading GPs…" : "Select a GP"}
            options={(gpList.data?.items ?? []).map((g) => ({ value: g.id, label: g.name, hint: g.lgdCode }))}
            onChange={(v) => setFilters({ gp: v })}
          />
        </div>
      </header>

      {!filters.gp ? (
        <Card>
          <EmptyState icon={MapPin} title="No GP selected" description="Choose a Gram Panchayat above, or open one from Block Insights or the search bar (Ctrl K)." />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !d ? (
        <PageSkeleton />
      ) : (
        <section aria-label={view.title} className="space-y-4">
          <p className="text-sm text-muted-foreground">{view.hint}</p>
          <ViewContent id={viewId} d={d} />
          {viewId === "summary" && <MoreViews viewHref={viewHref} />}
        </section>
      )}
    </div>
  );
}

function ViewContent({ id, d }: { id: GpViewId; d: GpDetailResponse }) {
  if (id === "summary") return <GpKpis d={d} />;
  return <GpUptimeSection uptime={d.uptime} gpName={d.gp.name} />;
}

/** Summary only: one line that points to the other view, so nothing on this page goes unnoticed. */
function MoreViews({ viewHref }: { viewHref: (id: string) => string }) {
  return (
    <nav aria-label="More in GP Insights" className="flex flex-wrap items-center gap-2 border-t border-border pt-4 text-sm">
      <span className="text-muted-foreground">More for this GP:</span>
      {GP_VIEWS.filter((v) => v.id !== "summary").map((v) => (
        <Link key={v.id} href={viewHref(v.id)} className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 font-medium hover:border-primary/40 hover:bg-primary-soft/40">
          {v.title} <ArrowRight className="size-3.5 text-primary" aria-hidden />
        </Link>
      ))}
    </nav>
  );
}
