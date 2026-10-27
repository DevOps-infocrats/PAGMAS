"use client";

import { useSearchParams } from "next/navigation";
import { ErrorState } from "@/components/feedback/states";
import { BlockFilter, CircleFilter, PeriodFilter } from "@/components/filters/filter-bar";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { RelatedViews, TitleBar, ViewHint } from "@/components/layout/page-header";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useDefaultSelection } from "@/hooks/use-default-selection";
import { useFilters } from "@/hooks/use-filters";
import { api, type BlockInsightsResponse } from "@/lib/api";
import { BLOCK_PATH, BLOCK_VIEWS, blockViewFrom, type BlockViewId } from "@/lib/block-views";
import { formatDate } from "@/lib/utils/format";
import type { GpSnapshot } from "@/types";
import { BlockUptimeSection } from "./block-charts";
import { BlockKpis } from "./block-kpis";

/**
 * Block Insights: a title bar (breadcrumb, block + view name, state / block pickers, "Open GP details",
 * compare week) and ONE view at a time, chosen from the sidebar sub-menu (?view=). Changing the state, block
 * or compare week keeps the view; opening a GP from any view goes straight to GP Insights, and Back returns
 * to the same view.
 */
export function BlockInsightsView() {
  const params = useSearchParams();
  const { filters, period, navigate, hrefTo } = useFilters();
  useDefaultSelection("block");
  const blockId = filters.block;
  const q = useApiQuery(blockId && period ? `block:${blockId}:${period.weekId}:${period.compareWeekId}` : null, () => api.getBlockInsights(blockId!, { weekId: period!.weekId, compareWeekId: period!.compareWeekId }));
  const data = q.data;
  const loading = q.loading || !period;
  const openGp = (gp: GpSnapshot) => navigate("/dashboard/gp-insights", { circle: gp.circleId, district: gp.districtId, block: gp.blockId, gp: gp.id });

  const viewId = blockViewFrom(params.get("view"));
  const view = BLOCK_VIEWS.find((v) => v.id === viewId)!;
  const viewHref = (id: string) => {
    const base = hrefTo(BLOCK_PATH);
    return `${base}${base.includes("?") ? "&" : "?"}view=${id}`;
  };

  return (
    <div className="space-y-5">
      {/* ---------------- Title bar: same in every view (scrolls with the page) ---------------- */}
      <TitleBar
        breadcrumbs={[
          { label: "Circle Overview", href: hrefTo("/dashboard") },
          ...(data
            ? [{ label: data.circle.name, href: hrefTo("/dashboard/circle-insights", { circle: data.circle.id, district: undefined, block: undefined }) }, { label: data.district.name }, { label: data.block.name }]
            : [{ label: "Block Insights" }]),
        ]}
        title={data ? `${data.block.name} block` : "Block Insights"}
        view={view.title}
        period={period ? `${period.week.label} · ${formatDate(period.week.startDate)} – ${formatDate(period.week.endDate)}` : "Loading period…"}
        note={data ? `${data.block.code} · ${data.district.name} district` : "Loading block…"}
      >
        {/* State / block / compare week change this page (the view is kept); "Open GP details" opens GP Insights */}
        <CircleFilter required className="sm:w-full" />
        <BlockFilter required allDistricts className="sm:w-full" />
        <SearchableSelect
          label="Open GP details"
          className="w-full"
          value={undefined}
          disabled={!data?.gps.length}
          placeholder={q.loading ? "Loading GPs…" : "Open GP details →"}
          options={[...(data?.gps ?? [])].sort((a, b) => a.name.localeCompare(b.name)).map((g) => ({ value: g.id, label: g.name, hint: g.lgdCode }))}
          onChange={(id) => {
            const gp = data?.gps.find((g) => g.id === id);
            if (gp) openGp(gp);
          }}
        />
        <PeriodFilter showWeek={false} fill />
      </TitleBar>

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <section key={viewId} aria-label={view.title} className="view-in space-y-4">
          <ViewHint>{view.hint}</ViewHint>
          <ViewContent id={viewId} data={data} loading={loading} />
          {viewId === "summary" && (
            <RelatedViews
              label="More in Block Insights"
              title="More for this block"
              items={BLOCK_VIEWS.filter((v) => v.id !== "summary").map((v) => ({ href: viewHref(v.id), title: v.title }))}
            />
          )}
        </section>
      )}
    </div>
  );
}

function ViewContent({ id, data, loading }: { id: BlockViewId; data: BlockInsightsResponse | undefined; loading: boolean }) {
  if (id === "summary") return <BlockKpis s={data?.summary} loading={loading} />;
  return <BlockUptimeSection data={data} loading={loading} />;
}

