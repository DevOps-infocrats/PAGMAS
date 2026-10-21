"use client";

import { ChevronLeft, ChevronRight, Download, ListX, Loader2, Search } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AvailabilityValue } from "@/components/feedback/badges";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/feedback/states";
import { BlockFilter, CircleFilter, DistrictFilter } from "@/components/filters/filter-bar";
import { Breadcrumbs } from "@/components/layout/page-header";
import { useMeta } from "@/components/providers/data-provider";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { AMC_PATH } from "@/lib/amc-views";
import { api, type KpiListItem, type KpiListKind, type KpiListQuery, type KpiListSort } from "@/lib/api";
import { KPI_LIST_GROUPS, KPI_LIST_PATH, KPI_LISTS, kpiListGroupFrom, kpiListKindFrom, stateDetailHref, type KpiListGroup } from "@/lib/kpi-lists";
import { OVERVIEW_VIEWS } from "@/lib/overview-views";
import { downloadKpiListXlsx } from "@/lib/reports/report-service";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate } from "@/lib/utils/format";

const PAGE_SIZE = 50;

type Col = { key: string; header: string; numeric?: boolean; render: (r: KpiListItem) => React.ReactNode };
const date = (v?: string | null) => (v ? formatDate(v) : "—");
const pct = (v?: number | null) => (v == null ? "NA" : `${v.toFixed(2)}%`);
const GP_COLS: Col[] = [
  { key: "name", header: "GP name", render: (r) => <span className="font-medium">{r.name}</span> },
  { key: "code", header: "GP code", render: (r) => <span className="text-muted-foreground">{r.code}</span> },
  { key: "circle", header: "State", render: (r) => r.circle },
  { key: "district", header: "District", render: (r) => r.district },
  { key: "block", header: "Block", render: (r) => r.block },
];
const BLOCK_COLS: Col[] = [
  { key: "name", header: "Block name", render: (r) => <span className="font-medium">{r.name}</span> },
  { key: "code", header: "Block code", render: (r) => <span className="text-muted-foreground">{r.code}</span> },
  { key: "circle", header: "State", render: (r) => r.circle },
  { key: "district", header: "District", render: (r) => r.district },
];
const MTD: Col = { key: "availability", header: "MTD %", numeric: true, render: (r) => <AvailabilityValue value={r.availability ?? null} /> };
const AMC_DATE: Col = { key: "amcDate", header: "AMC date", render: (r) => <span className="whitespace-nowrap">{date(r.amcDate)}</span> };

const AMC_PLAN_COLS: Col[] = [
  ...GP_COLS,
  { key: "category", header: "Plan type", render: (r) => <span className="whitespace-nowrap">{r.category ?? "—"}</span> },
  { key: "plannedDate", header: "Planned date", render: (r) => <span className="whitespace-nowrap">{date(r.plannedDate)}</span> },
  { key: "achDate", header: "Ach date", render: (r) => <span className={cn("whitespace-nowrap", r.achDate && "font-medium text-good-text")}>{date(r.achDate)}</span> },
  { key: "planStatus", header: "Current status", render: (r) => r.planStatus ?? "—" },
  { key: "letterStatus", header: "Letter status", render: (r) => r.letterStatus ?? "—" },
];
const PLANNED_SORTS: { value: KpiListSort; label: string }[] = [
  { value: "value-asc", label: "Earliest planned date first" },
  { value: "value-desc", label: "Latest planned date first" },
  { value: "name", label: "Name A–Z" },
];
const ACHIEVED_SORTS: { value: KpiListSort; label: string }[] = [
  { value: "value-desc", label: "Latest achieved first" },
  { value: "value-asc", label: "Earliest achieved first" },
  { value: "name", label: "Name A–Z" },
];

/** Columns and sort wording of each list (the backend sorts on the list's own measure). */
const LIST_UI: Record<KpiListKind, { cols: Col[]; sorts: { value: KpiListSort; label: string }[] }> = {
  "amc-plan-month": { cols: AMC_PLAN_COLS, sorts: PLANNED_SORTS },
  "amc-plan-mtd": { cols: AMC_PLAN_COLS, sorts: PLANNED_SORTS },
  "amc-achieved-mtd": { cols: AMC_PLAN_COLS, sorts: ACHIEVED_SORTS },
  "amc-plan-week": { cols: AMC_PLAN_COLS, sorts: PLANNED_SORTS },
  "amc-achieved-week": { cols: AMC_PLAN_COLS, sorts: ACHIEVED_SORTS },
  "amc-overdue": { cols: AMC_PLAN_COLS, sorts: PLANNED_SORTS },
  "gps-above-98": {
    cols: [...GP_COLS, AMC_DATE, MTD],
    sorts: [
      { value: "value-desc", label: "Highest availability first" },
      { value: "value-asc", label: "Lowest availability first" },
      { value: "name", label: "Name A–Z" },
    ],
  },
  "gps-at-zero": { cols: [...GP_COLS, AMC_DATE, MTD], sorts: [{ value: "name", label: "Name A–Z" }] },
  "penalty-blocks": {
    cols: [
      ...BLOCK_COLS,
      { key: "amcGps", header: "AMC GPs", numeric: true, render: (r) => formatCount(r.amcGps ?? null) },
      { key: "reportedGps", header: "Reporting GPs", numeric: true, render: (r) => formatCount(r.reportedGps ?? null) },
      MTD,
    ],
    sorts: [
      { value: "value-asc", label: "Lowest availability first" },
      { value: "value-desc", label: "Highest availability first" },
      { value: "name", label: "Name A–Z" },
    ],
  },
  "hoto-gps": {
    cols: [...GP_COLS, { key: "hotoDate", header: "HOTO date", render: (r) => <span className="whitespace-nowrap">{date(r.hotoDate)}</span> }, AMC_DATE],
    sorts: [
      { value: "name", label: "Name A–Z" },
      { value: "value-desc", label: "Latest HOTO first" },
      { value: "value-asc", label: "Earliest HOTO first" },
    ],
  },
  "existing-gps": {
    cols: [
      ...GP_COLS,
      { key: "status", header: "Status", render: (r) => <span className={cn("whitespace-nowrap", r.status !== "In scope" && "text-warning-text")}>{r.status ?? "—"}</span> },
      { key: "hotoDate", header: "HOTO date", render: (r) => <span className="whitespace-nowrap">{date(r.hotoDate)}</span> },
      AMC_DATE,
    ],
    sorts: [
      { value: "name", label: "Name A–Z" },
      { value: "value-desc", label: "Latest HOTO first" },
      { value: "value-asc", label: "Earliest HOTO first" },
    ],
  },
  "new-gp-blocks": {
    cols: [
      ...BLOCK_COLS,
      { key: "existingGps", header: "Existing GPs", numeric: true, render: (r) => formatCount(r.existingGps ?? null) },
      { key: "newGps", header: "New GPs", numeric: true, render: (r) => <span className="font-semibold">{formatCount(r.newGps ?? null)}</span> },
      { key: "totalGps", header: "Total GPs", numeric: true, render: (r) => formatCount(r.totalGps ?? null) },
    ],
    sorts: [
      { value: "value-desc", label: "Most new GPs first" },
      { value: "value-asc", label: "Fewest new GPs first" },
      { value: "name", label: "Name A–Z" },
    ],
  },
  "na-gps": { cols: [...GP_COLS, AMC_DATE], sorts: [{ value: "name", label: "Name A–Z" }] },
  "one-time-up": {
    cols: [...GP_COLS, { key: "availability", header: "Sept %", numeric: true, render: (r) => <AvailabilityValue value={r.availability ?? null} /> }],
    sorts: [
      { value: "value-desc", label: "Highest Sept availability first" },
      { value: "value-asc", label: "Lowest Sept availability first" },
      { value: "name", label: "Name A–Z" },
    ],
  },
  "hoto-pending-gps": {
    cols: [
      ...GP_COLS,
      { key: "amName", header: "Area manager", render: (r) => (r.amName ? r.amName : <span className="italic text-muted-foreground">Not assigned</span>) },
    ],
    sorts: [{ value: "name", label: "Name A–Z" }],
  },
  "removed-gps": {
    cols: [
      ...GP_COLS,
      { key: "status", header: "Reason", render: (r) => <span className="whitespace-nowrap text-warning-text">{r.status ?? "—"}</span> },
      { key: "remark", header: "Source remark", render: (r) => <span className="text-muted-foreground">{r.remark ?? "—"}</span> },
      { key: "hotoDate", header: "HOTO date", render: (r) => <span className="whitespace-nowrap">{date(r.hotoDate)}</span> },
      AMC_DATE,
    ],
    sorts: [
      { value: "value-asc", label: "Grouped by reason" },
      { value: "name", label: "Name A–Z" },
    ],
  },
  "hoto-blocks": {
    cols: [
      ...BLOCK_COLS,
      { key: "totalGps", header: "GPs in block", numeric: true, render: (r) => formatCount(r.totalGps ?? null) },
      { key: "hotoGps", header: "HOTO done GPs", numeric: true, render: (r) => formatCount(r.hotoGps ?? null) },
      { key: "hotoPct", header: "HOTO done %", numeric: true, render: (r) => pct(r.hotoPct) },
    ],
    sorts: [
      { value: "name", label: "Name A–Z" },
      { value: "value-asc", label: "Lowest HOTO % first" },
      { value: "value-desc", label: "Highest HOTO % first" },
    ],
  },
};

/**
 * The GPs / blocks behind a Circle Overview KPI card or table row (?kind=…, see KPI_LISTS).
 * Same rule and week as the card, so the unfiltered total equals the card. State / district / block
 * narrow the list (URL filters); search, sort and page are local. Excel = the whole filtered list.
 */
export function KpiListView() {
  const params = useSearchParams();
  const kind = kpiListKindFrom(params.get("kind"));
  if (!kind) {
    return (
      <Card>
        <EmptyState icon={ListX} title="Unknown list" description="Open a list from a KPI card on the Circle Overview." />
        <div className="pb-6 text-center">
          <Link href="/dashboard" className="text-sm font-medium text-primary hover:underline">
            Back to Circle Overview
          </Link>
        </div>
      </Card>
    );
  }
  const group = kpiListGroupFrom(params.get("group"));
  return <KpiList kind={kind} fromCircle={params.get("from") === "circle"} fromAmc={params.get("from") === "amc"} group={group && KPI_LIST_GROUPS[group].tabs.some((t) => t.kind === kind) ? group : null} />;
}

function KpiList({ kind, fromCircle, fromAmc, group }: { kind: KpiListKind; fromCircle: boolean; fromAmc: boolean; group: KpiListGroup | null }) {
  const { filters, period, navigate, hrefTo } = useFilters();
  const meta = useMeta();
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<KpiListSort | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);

  // Search waits until typing pauses; any change of the list's scope starts again on page 1.
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchText.trim()), 300);
    return () => clearTimeout(t);
  }, [searchText]);
  const scopeKey = `${kind}|${period?.weekId}|${filters.circle}|${filters.district}|${filters.block}|${search}|${sort}`;
  const [lastScope, setLastScope] = useState(scopeKey);
  if (scopeKey !== lastScope) {
    setLastScope(scopeKey);
    setPage(1);
  }

  const query: KpiListQuery | null = period
    ? { weekId: period.weekId, circleId: filters.circle, districtId: filters.district, blockId: filters.block, search: search || undefined, sort, page, pageSize: PAGE_SIZE }
    : null;
  const q = useApiQuery(query ? `kpi-list:${scopeKey}|${page}` : null, () => api.getKpiList(kind, query!));
  const d = q.data ?? q.staleData;
  const ui = LIST_UI[kind];
  const isBlock = (d?.unit ?? KPI_LISTS[kind].unit) === "block";
  const noun = isBlock ? "blocks" : "GPs";
  const filtered = !!(filters.circle || filters.district || filters.block || search);

  const open = (row: KpiListItem) =>
    isBlock
      ? navigate("/dashboard/block-insights", { circle: row.circleId, district: row.districtId, block: row.blockId, gp: undefined })
      : navigate("/dashboard/gp-insights", { circle: row.circleId, district: row.districtId, block: row.blockId, gp: row.id });

  const download = async () => {
    if (!query) return;
    setBusy(true);
    setMessage(null);
    try {
      const name = await downloadKpiListXlsx(kind, query);
      setMessage({ text: `Downloaded ${name} (${formatCount(d?.total ?? 0)} ${noun}).` });
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : "Download failed.", error: true });
    } finally {
      setBusy(false);
    }
  };

  // Back to the cards this list was opened from (same week): Circle Overview → Summary (all states), or –
  // when opened from Circle Insights – that state's Circle Insights → Summary.
  const summary = (base: string) => `${base}${base.includes("?") ? "&" : "?"}view=summary`;
  const overviewHref = summary(hrefTo("/dashboard", { circle: undefined, district: undefined, block: undefined, gp: undefined }));
  const stateName = meta?.circles.find((c) => c.id === filters.circle)?.name;
  const backToCircle = fromCircle && !!filters.circle;
  const circleHref = summary(hrefTo("/dashboard/circle-insights", { circle: filters.circle, district: undefined, block: undefined, gp: undefined }));
  // State pages (group) come from a Circle Overview view's table (States & Network Health, Handover & Scope): Back returns to that view.
  const overviewBase = hrefTo("/dashboard", { circle: undefined, district: undefined, block: undefined, gp: undefined });
  const groupView = group ? OVERVIEW_VIEWS.find((v) => v.id === KPI_LIST_GROUPS[group].view)! : null;
  const statesHref = `${overviewBase}${overviewBase.includes("?") ? "&" : "?"}view=${groupView?.id ?? "states"}`;
  // Lists opened from the AMC Conversion summary cards go back there (same week).
  const amcHref = summary(hrefTo(AMC_PATH, { circle: undefined, district: undefined, block: undefined, gp: undefined }));
  const backHref = group ? statesHref : fromAmc ? amcHref : backToCircle ? circleHref : overviewHref;
  const backLabel = groupView ? `Back to ${groupView.title}` : fromAmc ? "Back to AMC Conversion" : backToCircle ? `Back to ${stateName ?? "Circle Insights"}` : "Back to Circle Overview";
  const isHoto = ["hoto-gps", "hoto-blocks", "hoto-pending-gps", "existing-gps", "new-gp-blocks", "removed-gps"].includes(kind) || kind.startsWith("amc-");
  const tabHref = (k: KpiListKind) => stateDetailHref(hrefTo(KPI_LIST_PATH), group!, k);
  const insightsHref = hrefTo("/dashboard/circle-insights", { circle: filters.circle, district: undefined, block: undefined, gp: undefined });

  const from = d && d.total ? (d.page - 1) * d.pageSize + 1 : 0;
  const to = d ? Math.min(d.page * d.pageSize, d.total) : 0;

  return (
    <div className="space-y-5">
      {/* ---------------- Title bar ---------------- */}
      <header className="rounded-xl border border-border bg-card shadow-sm">
        <div className="space-y-0.5 px-4 py-2.5">
          <Breadcrumbs
            items={
              group
                ? [{ label: "Circle Overview", href: overviewHref }, { label: groupView!.title, href: statesHref }, { label: `${stateName ?? "All states"} – ${KPI_LIST_GROUPS[group].title}` }]
                : fromAmc
                  ? [{ label: "AMC Conversion Plan vs Execution", href: amcHref }, { label: d?.title ?? "GP list" }]
                  : [{ label: "Circle Overview", href: overviewHref }, ...(backToCircle ? [{ label: stateName ?? "Circle Insights", href: circleHref }] : []), { label: d?.title ?? "KPI list" }]
            }
          />
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <h1 className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-lg font-semibold leading-tight">
              {group ? `${stateName ?? "All states"} – ${KPI_LIST_GROUPS[group].title}` : (d?.title ?? "Loading list…")}
              {d && (
                <span className="text-[13px] font-normal text-muted-foreground">
                  {d.valueTotal != null ? `${formatCount(d.valueTotal)} new GPs in ${formatCount(d.total)} blocks` : `${formatCount(d.total)} ${noun}`}
                  {stateName ? ` in ${stateName}` : ""} · Week {d.week.number} · {isHoto ? "as of" : "MTD up to"} {formatDate(d.asOf)}
                </span>
              )}
            </h1>
            <div className="flex flex-wrap items-center gap-2">
              <Link href={backHref} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-accent">
                <ChevronLeft className="size-4" aria-hidden /> {backLabel}
              </Link>
              {group && filters.circle && (
                <Link href={insightsHref} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-medium hover:bg-accent">
                  Open Circle Insights <ChevronRight className="size-4" aria-hidden />
                </Link>
              )}
              <Button variant="primary" onClick={download} disabled={!d || busy || d.total === 0}>
                {busy ? <Loader2 className="animate-spin" /> : <Download />}
                {busy ? "Preparing Excel…" : "Download Excel"}
              </Button>
            </div>
          </div>
        </div>
        {group && (
          <nav aria-label="Lists for this state" className="flex flex-wrap gap-1.5 border-t border-border px-4 py-2">
            {KPI_LIST_GROUPS[group].tabs.map((t) => (
              <Link
                key={t.kind}
                href={tabHref(t.kind)}
                aria-current={t.kind === kind ? "page" : undefined}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  t.kind === kind ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                {t.label}
              </Link>
            ))}
          </nav>
        )}
        <div className="grid grid-cols-1 gap-x-4 gap-y-2 border-t border-border px-4 py-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <CircleFilter className="sm:w-full" />
          <DistrictFilter className="sm:w-full" />
          <BlockFilter className="sm:w-full" />
          <label className="flex min-w-0 flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Search</span>
            <span className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden />
              <Input value={searchText} onChange={(e) => setSearchText(e.target.value)} maxLength={80} placeholder={isBlock ? "Block name or code" : "GP name or code"} className="h-9 pl-8" />
            </span>
          </label>
        </div>
      </header>

      {d && <p className="text-sm text-muted-foreground">{d.rule}.</p>}

      {message && (
        <p role="status" className={cn("rounded-md border px-4 py-2.5 text-sm", message.error ? "border-critical/30 bg-critical-soft text-critical-text" : "border-good/30 bg-good-soft text-good-text")}>
          {message.text}
        </p>
      )}

      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !d ? (
        <Card className="p-4">
          <TableSkeleton rows={8} />
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-2.5 text-sm">
            <span>
              <b className="tabular">{formatCount(d.total)}</b> {noun}
              {filtered && <span className="text-muted-foreground"> of {formatCount(d.cardTotal)} in all states (filtered)</span>}
            </span>
            {ui.sorts.length > 1 && <Select ariaLabel="Sort the list" className="w-56" value={d.sort} options={ui.sorts} onValueChange={(v) => setSort(v as KpiListSort)} />}
          </div>
          {d.total === 0 ? (
            <EmptyState icon={ListX} title={`No ${noun} in this list`} description={filtered ? "Nothing matches the chosen state / district / block or search." : "No item meets this KPI's rule for the selected week."} />
          ) : (
            <div className={cn("overflow-x-auto", q.loading && "opacity-60 transition-opacity")}>
              <table className="w-full text-[13px]">
                <caption className="sr-only">{d.title}</caption>
                <thead>
                  <tr className="border-b border-border bg-muted/60 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    <th scope="col" className="px-3 py-2 text-right">
                      #
                    </th>
                    {ui.cols.map((c) => (
                      <th key={c.key} scope="col" className={cn("px-3 py-2", c.numeric && "text-right")}>
                        {c.header}
                      </th>
                    ))}
                    <th scope="col" className="px-3 py-2">
                      <span className="sr-only">Open</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {d.items.map((row, i) => (
                    <tr
                      key={row.id}
                      tabIndex={0}
                      aria-label={`Open ${isBlock ? "Block" : "GP"} Insights for ${row.name}`}
                      onClick={() => open(row)}
                      onKeyDown={(e) => e.key === "Enter" && open(row)}
                      className="cursor-pointer border-b border-border/70 last:border-0 hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
                    >
                      <td className="px-3 py-2 text-right text-muted-foreground">{from + i}</td>
                      {ui.cols.map((c) => (
                        <td key={c.key} className={cn("px-3 py-2", c.numeric && "text-right")}>
                          {c.render(row)}
                        </td>
                      ))}
                      <td className="px-3 py-2 text-right text-xs font-semibold text-primary">Open →</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {d.total > 0 && (
            <nav aria-label="List pages" className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm">
              <span className="text-muted-foreground">
                Showing {formatCount(from)}–{formatCount(to)} of {formatCount(d.total)}
              </span>
              <span className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={() => setPage(d.page - 1)} disabled={d.page <= 1 || q.loading}>
                  <ChevronLeft /> Previous
                </Button>
                <span className="tabular text-muted-foreground">
                  Page {d.page} of {d.pages}
                </span>
                <Button variant="outline" size="sm" onClick={() => setPage(d.page + 1)} disabled={d.page >= d.pages || q.loading}>
                  Next <ChevronRight />
                </Button>
              </span>
            </nav>
          )}
        </Card>
      )}
    </div>
  );
}
