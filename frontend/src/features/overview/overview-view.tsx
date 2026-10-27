"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { ErrorState } from "@/components/feedback/states";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { RelatedViews, TitleBar, ViewHint } from "@/components/layout/page-header";
import { useMeta } from "@/components/providers/data-provider";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { api, type KpiListKind } from "@/lib/api";
import { KPI_LIST_PATH, stateDetailHref, type KpiListGroup } from "@/lib/kpi-lists";
import { OVERVIEW_PATH, OVERVIEW_VIEWS, overviewViewFrom, type OverviewViewId } from "@/lib/overview-views";
import { formatDate } from "@/lib/utils/format";
import { ConvertedGps, HotoProgress, NetworkHealth } from "./overview-charts";
import { OverviewKpis } from "./overview-kpis";
import { StateComparison } from "./state-comparison";

/**
 * Circle Overview: a slim sticky title bar (page + view name, period, "Open state details") and ONE view at a
 * time, chosen from the sidebar sub-menu (?view=). Opening a state from any view goes straight to Circle
 * Insights; the browser Back button returns to the same view.
 */
export function OverviewView() {
  const meta = useMeta();
  const params = useSearchParams();
  const router = useRouter();
  const { period, navigate, hrefTo } = useFilters();
  const q = useApiQuery(period ? `overview:${period.weekId}:${period.compareWeekId}` : null, () =>
    api.getOverview({ weekId: period!.weekId, compareWeekId: period!.compareWeekId }),
  );
  const data = q.data;
  const openCircle = (circleId: string) => navigate("/dashboard/circle-insights", { circle: circleId, district: undefined, block: undefined, gp: undefined });
  // Table rows of the States & Network Health and Handover & Scope views open the state's own page (lists as tabs, same week).
  const openState = (circleId: string, group: KpiListGroup, kind?: KpiListKind) =>
    router.push(stateDetailHref(hrefTo(KPI_LIST_PATH, { circle: circleId, district: undefined, block: undefined, gp: undefined }), group, kind));
  // Still loading while the reporting period (from /meta) is not known yet.
  const loading = q.loading || !period;
  const props = { data, loading, onOpenCircle: openCircle, onOpenState: openState };

  const viewId = overviewViewFrom(params.get("view"));
  const view = OVERVIEW_VIEWS.find((v) => v.id === viewId)!;
  const viewHref = (id: string) => {
    const base = hrefTo(OVERVIEW_PATH);
    return `${base}${base.includes("?") ? "&" : "?"}view=${id}`;
  };

  return (
    <div className="space-y-5">
      {/* ---------------- Sticky title bar: stays on top in every view ---------------- */}
      <TitleBar
        title="Circle Overview"
        view={view.title}
        period={period ? `${period.week.label} · ${formatDate(period.week.startDate)} – ${formatDate(period.week.endDate)}` : "Loading period…"}
        note={`All states${data?.asOf ? ` · figures as of ${formatDate(data.asOf)}` : ""}`}
        aside={
          <SearchableSelect
            label="Open state details"
            hideLabel
            className="w-full sm:w-60"
            value={undefined}
            placeholder="Open state details →"
            options={(meta?.circles ?? []).map((c) => ({ value: c.id, label: c.name, hint: c.code }))}
            onChange={(v) => v && openCircle(v)}
          />
        }
      />

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <section key={viewId} aria-label={view.title} className="view-in space-y-4">
          <ViewHint>{view.hint}</ViewHint>
          <ViewContent id={viewId} props={props} />
          {viewId === "summary" && (
            <RelatedViews
              label="More in Circle Overview"
              title="More in this overview"
              items={OVERVIEW_VIEWS.filter((v) => v.id !== "summary").map((v) => ({ href: viewHref(v.id), title: v.title }))}
            />
          )}
        </section>
      )}
    </div>
  );
}

type ViewProps = Parameters<typeof NetworkHealth>[0];

function ViewContent({ id, props }: { id: OverviewViewId; props: ViewProps }) {
  const { data, loading } = props;
  if (id === "summary") return <OverviewKpis s={data?.summary} states={data?.stateDetails} asOf={data?.asOf} loading={loading} />;
  if (id === "states") return <NetworkHealth {...props} />;
  if (id === "comparison") return <StateComparison data={data} loading={loading} />;
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <HotoProgress {...props} />
      <ConvertedGps {...props} />
    </div>
  );
}

