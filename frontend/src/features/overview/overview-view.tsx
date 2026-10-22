"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { DemoBadge } from "@/components/feedback/badges";
import { ErrorState } from "@/components/feedback/states";
import { SearchableSelect } from "@/components/filters/searchable-select";
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
      <header className="sticky top-16 z-20 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-xl border border-border bg-card/95 px-4 py-2.5 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-card/85">
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-x-2 text-lg font-semibold leading-tight">
            Circle Overview
            <span className="text-subtle-foreground" aria-hidden>
              ·
            </span>
            <span className="text-primary">{view.title}</span>
          </h1>
          <p className="truncate text-[13px] text-muted-foreground">
            {period ? `All states · ${period.week.label} (${formatDate(period.week.startDate)} – ${formatDate(period.week.endDate)})${data?.asOf ? ` · figures as of ${formatDate(data.asOf)}` : ""}` : "All states"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <DemoBadge />
          <SearchableSelect
            label="Open state details"
            hideLabel
            className="w-full sm:w-60"
            value={undefined}
            placeholder="Open state details →"
            options={(meta?.circles ?? []).map((c) => ({ value: c.id, label: c.name, hint: c.code }))}
            onChange={(v) => v && openCircle(v)}
          />
        </div>
      </header>

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : (
        <section aria-label={view.title} className="space-y-4">
          <p className="text-sm text-muted-foreground">{view.hint}</p>
          <ViewContent id={viewId} props={props} />
          {viewId === "summary" && <MoreViews viewHref={viewHref} />}
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
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <HotoProgress {...props} />
      <ConvertedGps {...props} />
    </div>
  );
}

/** Summary only: one line that points to the other views, so nothing on the overview goes unnoticed. */
function MoreViews({ viewHref }: { viewHref: (id: string) => string }) {
  return (
    <nav aria-label="More in Circle Overview" className="flex flex-wrap items-center gap-2 border-t border-border pt-4 text-sm">
      <span className="text-muted-foreground">More in this overview:</span>
      {OVERVIEW_VIEWS.filter((v) => v.id !== "summary").map((v) => (
        <Link key={v.id} href={viewHref(v.id)} className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-3 py-1.5 font-medium hover:border-primary/40 hover:bg-primary-soft/40">
          {v.title} <ArrowRight className="size-3.5 text-primary" aria-hidden />
        </Link>
      ))}
    </nav>
  );
}
