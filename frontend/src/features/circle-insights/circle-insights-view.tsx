"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { DemoBadge } from "@/components/feedback/badges";
import { ErrorState } from "@/components/feedback/states";
import { CircleFilter } from "@/components/filters/filter-bar";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { Breadcrumbs } from "@/components/layout/page-header";
import { useMeta } from "@/components/providers/data-provider";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useDefaultSelection } from "@/hooks/use-default-selection";
import { useFilters } from "@/hooks/use-filters";
import { api, type CircleInsightsResponse } from "@/lib/api";
import { CIRCLE_PATH, CIRCLE_VIEWS, circleViewFrom, type CircleViewId } from "@/lib/circle-views";
import { formatDate } from "@/lib/utils/format";
import type { BlockSummary } from "@/types";
import { BlockGpCount, HotoAmcStatus, UptimeSection } from "./circle-charts";
import { CircleKpis } from "./circle-kpis";

/**
 * Circle Insights: a slim title bar (breadcrumb, state + view name, state picker, "Open block details")
 * and ONE view at a time, chosen from the sidebar sub-menu (?view=). Changing the state or week keeps the view;
 * opening a block from any view goes straight to Block Insights, and Back returns to the same view.
 */
export function CircleInsightsView() {
  const meta = useMeta();
  const params = useSearchParams();
  const { filters, period, navigate, hrefTo } = useFilters();
  useDefaultSelection("circle");
  const circleId = filters.circle;
  const q = useApiQuery(circleId && period ? `circle:${circleId}:${period.weekId}:${period.compareWeekId}` : null, () =>
    api.getCircleInsights(circleId!, { weekId: period!.weekId, compareWeekId: period!.compareWeekId }),
  );
  const data = q.data;
  const loading = q.loading || !period || !circleId;
  const circleName = data?.circle.name ?? meta?.circles.find((c) => c.id === circleId)?.name;
  const openBlock = (b: Pick<BlockSummary, "id" | "districtId">) =>
    navigate("/dashboard/block-insights", { circle: circleId, district: b.districtId, block: b.id, gp: undefined });

  const viewId = circleViewFrom(params.get("view"));
  const view = CIRCLE_VIEWS.find((v) => v.id === viewId)!;
  const viewHref = (id: string) => {
    const base = hrefTo(CIRCLE_PATH);
    return `${base}${base.includes("?") ? "&" : "?"}view=${id}`;
  };

  return (
    <div className="space-y-5">
      {/* ---------------- Title bar: same in every view (scrolls with the page) ---------------- */}
      <header className="space-y-1 rounded-xl border border-border bg-card px-4 py-2.5 shadow-sm">
        <Breadcrumbs items={[{ label: "Circle Overview", href: "/dashboard" }, { label: "Circle Insights" }, ...(circleName ? [{ label: circleName }] : [])]} />
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="min-w-0">
            <h1 className="flex flex-wrap items-center gap-x-2 text-lg font-semibold leading-tight">
              {circleName ?? "Circle Insights"}
              <span className="text-subtle-foreground" aria-hidden>
                ·
              </span>
              <span className="text-primary">{view.title}</span>
            </h1>
            <p className="truncate text-[13px] text-muted-foreground">
              {period
                ? `${period.week.label} · ${formatDate(period.week.startDate)} – ${formatDate(period.week.endDate)}${data?.asOf ? ` · figures as of ${formatDate(data.asOf)}` : ""}`
                : "Loading period…"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <DemoBadge />
            {/* Changes the state on this page (keeps the view) */}
            <span className="text-xs font-medium text-muted-foreground" aria-hidden>
              State
            </span>
            <CircleFilter required hideLabel className="w-full sm:w-44" />
            {/* Opens Block Insights for the chosen block */}
            <SearchableSelect
              label="Open block details"
              hideLabel
              className="w-full sm:w-56"
              value={undefined}
              disabled={!meta || !circleId}
              placeholder="Open block details →"
              options={(meta?.blocks ?? []).filter((b) => b.circleId === circleId).map((b) => ({ value: b.id, label: b.name, hint: b.code }))}
              onChange={(id) => {
                const b = meta?.blocks.find((x) => x.id === id);
                if (b) openBlock(b);
              }}
            />
          </div>
        </div>
      </header>

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <section aria-label={view.title} className="space-y-4">
          <p className="text-sm text-muted-foreground">{view.hint}</p>
          <ViewContent id={viewId} data={data} loading={loading} circleName={circleName} onOpenBlock={openBlock} />
          {viewId === "summary" && <MoreViews viewHref={viewHref} />}
        </section>
      )}
    </div>
  );
}

function ViewContent({
  id,
  data,
  loading,
  circleName,
  onOpenBlock,
}: {
  id: CircleViewId;
  data: CircleInsightsResponse | undefined;
  loading: boolean;
  circleName: string | undefined;
  onOpenBlock: (b: BlockSummary) => void;
}) {
  if (id === "summary") return <CircleKpis s={data?.summary} loading={loading} stateName={circleName} asOf={data?.asOf} circleId={data?.circle.id} />;
  if (id === "blocks") return <BlockGpCount data={data} loading={loading} onOpen={onOpenBlock} />;
  if (id === "hoto") return <HotoAmcStatus data={data} loading={loading} stateName={circleName} />;
  if (id === "gp-uptime") return <UptimeSection kind="gp" data={data} loading={loading} stateName={circleName} />;
  return <UptimeSection kind="block" data={data} loading={loading} stateName={circleName} />;
}

/** Summary only: one line that points to the other views, so nothing on this page goes unnoticed. */
function MoreViews({ viewHref }: { viewHref: (id: string) => string }) {
  return (
    <nav aria-label="More in Circle Insights" className="flex flex-wrap items-center gap-2 border-t border-border pt-4 text-sm">
      <span className="text-muted-foreground">More for this state:</span>
      {CIRCLE_VIEWS.filter((v) => v.id !== "summary").map((v) => (
        <Link key={v.id} href={viewHref(v.id)} className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 font-medium hover:border-primary/40 hover:bg-primary-soft/40">
          {v.title} <ArrowRight className="size-3.5 text-primary" aria-hidden />
        </Link>
      ))}
    </nav>
  );
}
