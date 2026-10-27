"use client";

import { MapPin } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { LifecycleBadge } from "@/components/feedback/badges";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { BlockFilter, CircleFilter, DistrictFilter } from "@/components/filters/filter-bar";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { RelatedViews, TitleBar, ViewHint } from "@/components/layout/page-header";
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
      <TitleBar
        breadcrumbs={[
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
        title={d ? d.gp.name : "GP Insights"}
        view={view.title}
        period={period ? `${period.week.label} · ${formatDate(period.week.startDate)} – ${formatDate(period.week.endDate)}` : "Loading period…"}
        note={d ? `LGD ${d.gp.lgdCode} · ID ${d.gp.id.toUpperCase()}` : "Select a Gram Panchayat to see its details."}
        aside={d && <LifecycleBadge status={d.gp.lifecycle} />}
      >
        {/* All pickers change this page; the view is kept */}
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
      </TitleBar>

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
        <section key={viewId} aria-label={view.title} className="view-in space-y-4">
          <ViewHint>{view.hint}</ViewHint>
          <ViewContent id={viewId} d={d} />
          {viewId === "summary" && (
            <RelatedViews
              label="More in GP Insights"
              title="More for this GP"
              items={GP_VIEWS.filter((v) => v.id !== "summary").map((v) => ({ href: viewHref(v.id), title: v.title }))}
            />
          )}
        </section>
      )}
    </div>
  );
}

function ViewContent({ id, d }: { id: GpViewId; d: GpDetailResponse }) {
  if (id === "summary") return <GpKpis d={d} />;
  return <GpUptimeSection uptime={d.uptime} gpName={d.gp.name} />;
}

