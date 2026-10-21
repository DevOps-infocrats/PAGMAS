"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ErrorState } from "@/components/feedback/states";
import { BlockFilter, CircleFilter, PeriodFilter } from "@/components/filters/filter-bar";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { Breadcrumbs } from "@/components/layout/page-header";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useDefaultSelection } from "@/hooks/use-default-selection";
import { useFilters } from "@/hooks/use-filters";
import { api, type BlockInsightsResponse } from "@/lib/api";
import { BLOCK_PATH, BLOCK_VIEWS, blockViewFrom, type BlockViewId } from "@/lib/block-views";
import { formatDate } from "@/lib/utils/format";
import type { GpSnapshot } from "@/types";
import { BlockUptimeSection, OltDistribution } from "./block-charts";
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
      <header className="rounded-xl border border-border bg-card shadow-sm">
        <div className="space-y-0.5 px-4 py-2.5">
          <Breadcrumbs
            items={[
              { label: "Circle Overview", href: hrefTo("/dashboard") },
              ...(data
                ? [{ label: data.circle.name, href: hrefTo("/dashboard/circle-insights", { circle: data.circle.id, district: undefined, block: undefined }) }, { label: data.district.name }, { label: data.block.name }]
                : [{ label: "Block Insights" }]),
            ]}
          />
          {/* title and its context on one line ("data as of" is already in the top header) */}
          <h1 className="flex flex-wrap items-baseline gap-x-2 text-lg font-semibold leading-tight">
            {data ? `${data.block.name} block` : "Block Insights"}
            <span className="text-subtle-foreground" aria-hidden>
              ·
            </span>
            <span className="text-primary">{view.title}</span>
            <span className="text-[13px] font-normal text-muted-foreground">
              {data && period ? `${data.block.code} · ${data.district.name} district · ${period.week.label} (${formatDate(period.week.startDate)} – ${formatDate(period.week.endDate)})` : "Loading block…"}
            </span>
          </h1>
        </div>
        {/* State / block / compare week change this page (the view is kept); "Open GP details" opens GP Insights */}
        {/* four equal columns: every control lines up and none is squeezed */}
        <div className="grid grid-cols-1 gap-x-4 gap-y-2 border-t border-border px-4 py-2.5 sm:grid-cols-2 lg:grid-cols-4">
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
        </div>
      </header>

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <section aria-label={view.title} className="space-y-4">
          <p className="text-sm text-muted-foreground">{view.hint}</p>
          <ViewContent id={viewId} data={data} loading={loading} onOpenGp={openGp} />
          {viewId === "summary" && <MoreViews viewHref={viewHref} />}
        </section>
      )}
    </div>
  );
}

function ViewContent({ id, data, loading, onOpenGp }: { id: BlockViewId; data: BlockInsightsResponse | undefined; loading: boolean; onOpenGp: (gp: GpSnapshot) => void }) {
  if (id === "summary") return <BlockKpis s={data?.summary} loading={loading} groups={data?.amcGroups} gps={data?.gps ?? []} onOpenGp={onOpenGp} />;
  if (id === "gp-uptime") return <BlockUptimeSection data={data} loading={loading} />;
  return <OltDistribution data={data} loading={loading} />;
}

/** Summary only: one line that points to the other views, so nothing on this page goes unnoticed. */
function MoreViews({ viewHref }: { viewHref: (id: string) => string }) {
  return (
    <nav aria-label="More in Block Insights" className="flex flex-wrap items-center gap-2 border-t border-border pt-4 text-sm">
      <span className="text-muted-foreground">More for this block:</span>
      {BLOCK_VIEWS.filter((v) => v.id !== "summary").map((v) => (
        <Link key={v.id} href={viewHref(v.id)} className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 font-medium hover:border-primary/40 hover:bg-primary-soft/40">
          {v.title} <ArrowRight className="size-3.5 text-primary" aria-hidden />
        </Link>
      ))}
    </nav>
  );
}
