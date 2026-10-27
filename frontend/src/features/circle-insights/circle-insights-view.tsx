"use client";

import { useSearchParams } from "next/navigation";
import { ErrorState } from "@/components/feedback/states";
import { CircleFilter } from "@/components/filters/filter-bar";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { RelatedViews, TitleBar, ViewHint } from "@/components/layout/page-header";
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
      <TitleBar
        breadcrumbs={[{ label: "Circle Overview", href: "/dashboard" }, { label: "Circle Insights" }, ...(circleName ? [{ label: circleName }] : [])]}
        title={circleName ?? "Circle Insights"}
        view={view.title}
        period={period ? `${period.week.label} · ${formatDate(period.week.startDate)} – ${formatDate(period.week.endDate)}` : "Loading period…"}
        note={data?.asOf ? `Figures as of ${formatDate(data.asOf)}` : undefined}
      >
        {/* Changes the state on this page (keeps the view) */}
        <CircleFilter required label="State" className="sm:w-full" />
        {/* Opens Block Insights for the chosen block */}
        <SearchableSelect
          label="Open block details"
          className="w-full"
          value={undefined}
          disabled={!meta || !circleId}
          placeholder="Choose a block →"
          options={(meta?.blocks ?? []).filter((b) => b.circleId === circleId).map((b) => ({ value: b.id, label: b.name, hint: b.code }))}
          onChange={(id) => {
            const b = meta?.blocks.find((x) => x.id === id);
            if (b) openBlock(b);
          }}
        />
      </TitleBar>

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <section key={viewId} aria-label={view.title} className="view-in space-y-4">
          <ViewHint>{view.hint}</ViewHint>
          <ViewContent id={viewId} data={data} loading={loading} circleName={circleName} onOpenBlock={openBlock} />
          {viewId === "summary" && (
            <RelatedViews
              label="More in Circle Insights"
              title="More for this state"
              items={CIRCLE_VIEWS.filter((v) => v.id !== "summary").map((v) => ({ href: viewHref(v.id), title: v.title }))}
            />
          )}
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

