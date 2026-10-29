"use client";

import { Ban, BoxSelect, ChevronDown, ChevronLeft, ChevronRight, CircleCheckBig, Clock, Download, ListX, Loader2, MapPin, Search, ShieldCheck, ShieldOff, Wrench, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, useEffect, useState } from "react";
import { AvailabilityValue } from "@/components/feedback/badges";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/feedback/states";
import { BlockFilter, CircleFilter, DistrictFilter } from "@/components/filters/filter-bar";
import { TitleBar, ViewHint } from "@/components/layout/page-header";
import { useMeta } from "@/components/providers/data-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import { Select } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { AMC_PATH } from "@/lib/amc-views";
import { api, type KpiListItem, type KpiListKind, type KpiListQuery, type KpiListResponse, type KpiListSort, type OverviewResponse } from "@/lib/api";
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
// HOTO Done GPs: both date cells turn light green when the HOTO date equals the AMC date (two missing dates never match).
const sameHotoAmcDate = (r: KpiListItem) => !!r.hotoDate && !!r.amcSourceDate && r.hotoDate === r.amcSourceDate;
const MATCH_CELL = "rounded-sm bg-good-soft px-1 text-good-text";
const HOTO_AMC_DATE: Col = {
  key: "amcSourceDate",
  header: "AMC date",
  render: (r) => <span className={cn("whitespace-nowrap", sameHotoAmcDate(r) && MATCH_CELL)}>{date(r.amcSourceDate)}</span>,
};
const SAME_HANDOVER_AMC_DATE: Col = {
  key: "hotoDate",
  header: "HOTO date",
  render: (r) => <span className={cn("whitespace-nowrap", sameHotoAmcDate(r) && MATCH_CELL)}>{date(r.hotoDate)}</span>,
};

const AMC_PLAN_COLS: Col[] = [
  ...GP_COLS,
  { key: "category", header: "Plan type", render: (r) => <span className="whitespace-nowrap">{r.category ?? "—"}</span> },
  { key: "plannedDate", header: "Planned date", render: (r) => <span className="whitespace-nowrap">{date(r.plannedDate)}</span> },
  { key: "achDate", header: "Ach date", render: (r) => <span className={cn("whitespace-nowrap", r.achDate && "font-medium text-good-text")}>{date(r.achDate)}</span> },
  { key: "planStatus", header: "Current status", render: (r) => r.planStatus ?? "—" },
  { key: "letterStatus", header: "Letter status", render: (r) => r.letterStatus ?? "—" },
  { key: "approvalStatus", header: "Approval status", render: (r) => r.approvalStatus ?? "—" },
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
    cols: [...GP_COLS, SAME_HANDOVER_AMC_DATE, HOTO_AMC_DATE],
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
      { key: "reason", header: "Reason", render: (r) => r.reason ?? "Not Specified" },
    ],
    sorts: [{ value: "name", label: "Name A–Z" }],
  },
  "hoto-pending-blocks": {
    cols: [
      ...BLOCK_COLS,
      { key: "totalGps", header: "GPs in block", numeric: true, render: (r) => formatCount(r.totalGps ?? null) },
      { key: "revisedGps", header: "Revised existing GPs", numeric: true, render: (r) => formatCount(r.revisedGps ?? null) },
      { key: "hoto", header: "HOTO", render: () => <span className="whitespace-nowrap font-medium text-warning-text">Not done</span> },
    ],
    sorts: [{ value: "name", label: "Name A–Z" }],
  },
  "all-blocks": {
    cols: [
      ...BLOCK_COLS,
      { key: "totalGps", header: "GPs in block", numeric: true, render: (r) => formatCount(r.totalGps ?? null) },
      { key: "hotoGps", header: "HOTO done GPs", numeric: true, render: (r) => formatCount(r.hotoGps ?? null) },
      { key: "amcOriginalGps", header: "AMC at HOTO", numeric: true, render: (r) => formatCount(r.amcOriginalGps ?? null) },
      { key: "incrementalGps", header: "Incremental", numeric: true, render: (r) => formatCount(r.incrementalGps ?? null) },
      { key: "totalAmcGps", header: "Total AMC GPs", numeric: true, render: (r) => formatCount(r.totalAmcGps ?? null) },
      { key: "nonAmcGps", header: "Non-AMC GPs", numeric: true, render: (r) => formatCount(r.nonAmcGps ?? null) },
    ],
    sorts: [{ value: "name", label: "Name A–Z" }],
  },
  "non-amc-gps": {
    cols: [
      ...GP_COLS,
      {
        key: "hotoStatus",
        header: "HOTO",
        render: (r) => <span className={cn("whitespace-nowrap font-medium", r.hotoStatus === "Done" ? "text-good-text" : "text-warning-text")}>{r.hotoStatus ?? "—"}</span>,
      },
      { key: "hotoDate", header: "HOTO date", render: (r) => <span className="whitespace-nowrap">{date(r.hotoDate)}</span> },
    ],
    sorts: [{ value: "name", label: "Name A–Z" }],
  },
  "amc-original-gps": {
    cols: [...GP_COLS, AMC_DATE, MTD],
    sorts: [
      { value: "name", label: "Name A–Z" },
      { value: "value-desc", label: "Name Z–A" },
    ],
  },
  "incremental-gps": {
    cols: [...GP_COLS, AMC_DATE, MTD],
    sorts: [
      { value: "name", label: "Name A–Z" },
      { value: "value-desc", label: "Name Z–A" },
    ],
  },
  "amc-gps": {
    cols: [
      ...GP_COLS,
      { key: "category", header: "AMC / Incremental", render: (r) => r.category ?? "AMC" },
      { key: "hotoDate", header: "HOTO date", render: (r) => <span className="whitespace-nowrap">{date(r.hotoDate)}</span> },
      AMC_DATE,
    ],
    sorts: [
      { value: "name", label: "Name A–Z" },
      { value: "value-asc", label: "Earliest AMC date first" },
      { value: "value-desc", label: "Latest AMC date first" },
    ],
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
      { key: "gpDetails", header: "GPs within block", render: (r) => formatCount(r.gpDetails?.length ?? 0) },
    ],
    sorts: [
      { value: "name", label: "Name A–Z" },
      { value: "value-asc", label: "Lowest HOTO % first" },
      { value: "value-desc", label: "Highest HOTO % first" },
    ],
  },
};


/** One KPI tile of a list page (same look as the All Blocks strip): colour line, icon, value and an optional
 *  Done / Pending style breakdown. With `href` the whole tile is a link (tab or state filter). */
type KpiPart = { label: string; value: number | null | undefined; color: string };
type KpiTileData = { label: string; value: number | null | undefined; color: string; icon: LucideIcon; parts?: KpiPart[]; href?: string; active?: boolean };

function KpiTile({ t }: { t: KpiTileData }) {
  const Icon = t.icon;
  const body = (
    <>
      <span className="absolute inset-x-0 top-0 h-[3px]" style={{ background: t.color }} aria-hidden />
      <span
        className="flex size-7 shrink-0 items-center justify-center rounded-md"
        style={{ background: `color-mix(in srgb, ${t.color} 14%, transparent)`, color: t.color }}
        aria-hidden
      >
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">{t.label}</p>
        <p className="tabular text-[18px] font-bold leading-tight text-heading">{formatCount(t.value)}</p>
        {t.parts && (
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11.5px]">
            {t.parts.map((p) => (
              <span key={p.label} className="inline-flex items-center gap-1 whitespace-nowrap">
                <span className="size-2 rounded-full" style={{ background: p.color }} aria-hidden />
                <span className="text-muted-foreground">{p.label}</span>
                <span className="tabular font-bold text-heading">{formatCount(p.value)}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </>
  );
  const cls = cn(
    "relative flex items-start gap-2.5 overflow-hidden rounded-lg border bg-card px-3 py-2.5 shadow-xs",
    t.active ? "border-primary ring-1 ring-primary/40" : "border-border",
    t.href && "transition-colors hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-2 focus-visible:outline-primary",
  );
  return t.href ? (
    <Link href={t.href} className={cls} aria-current={t.active ? "true" : undefined}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

const STRIP_COLS: Record<number, string> = {
  3: "grid-cols-1 sm:grid-cols-3",
  4: "grid-cols-2 lg:grid-cols-4",
  5: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5",
  6: "grid-cols-2 sm:grid-cols-3 xl:grid-cols-6",
};

function KpiStrip({ label, overall, states }: { label: string; overall: KpiTileData[]; states?: KpiTileData[] }) {
  return (
    <section aria-label={label} className="space-y-2">
      <div className={cn("grid gap-2", STRIP_COLS[overall.length] ?? STRIP_COLS[6])}>
        {overall.map((t) => (
          <KpiTile key={t.label} t={t} />
        ))}
      </div>
      {states && states.length > 0 && (
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          {states.map((t) => (
            <KpiTile key={t.label} t={t} />
          ))}
        </div>
      )}
    </section>
  );
}

const TONE = {
  total: "var(--series-7)",
  done: "var(--good)",
  pending: "var(--warning)",
  removed: "var(--critical)",
  amcAtHoto: "var(--series-2)",
  incremental: "var(--series-4)",
  totalAmc: "var(--series-3)",
  nonAmc: "var(--na)",
  state: "var(--series-1)",
};

/** KPI strip at the top of the All Blocks list – aggregated across all filtered blocks. */
function AllBlocksKpiStrip({ s }: { s: NonNullable<KpiListResponse["blockSummary"]> }) {
  return (
    <KpiStrip
      label="All blocks summary"
      overall={[
        { label: "Total Blocks", value: s.totalBlocks, color: TONE.total, icon: BoxSelect },
        { label: "HOTO Done Blocks", value: s.hotoDoneBlocks, color: TONE.done, icon: CircleCheckBig },
        { label: "AMC at HOTO", value: s.amcOriginalGps, color: TONE.amcAtHoto, icon: ShieldCheck },
        { label: "Incremental AMC", value: s.incrementalGps, color: TONE.incremental, icon: Wrench },
        { label: "Total AMC GPs", value: s.totalAmcGps, color: TONE.totalAmc, icon: Wrench },
        { label: "Non-AMC GPs", value: s.nonAmcGps, color: TONE.nonAmc, icon: ShieldOff },
      ]}
    />
  );
}

type OverviewState = NonNullable<OverviewResponse["stateDetails"]>[number];
const STATE_ORDER = ["Rajasthan", "Assam", "Haryana"];

/**
 * KPI strip of the HOTO blocks, HOTO GPs and AMC GPs pages: all-state totals (a card opens its tab) and one card
 * per state (filters the list to that state; click again for all states). Every breakdown adds up:
 * blocks = done + pending; existing GPs = HOTO done + pending + NP/closed = AMC at HOTO + incremental + non-AMC + NP/closed.
 */
function DetailKpiStrip({
  group,
  kind,
  summary,
  states,
  activeState,
  tabHref,
  stateHref,
}: {
  group: "hotoBlocks" | "hotoGps" | "amcGps";
  kind: KpiListKind;
  summary: OverviewResponse["summary"] | undefined;
  states: OverviewState[];
  activeState: string | undefined;
  tabHref: (k: KpiListKind) => string;
  stateHref: (circleId: string | undefined) => string;
}) {
  if (!summary) return <div className="text-sm text-muted-foreground">Loading KPI summary…</div>;
  const ordered = STATE_ORDER.map((name) => states.find((st) => st.name.toLowerCase() === name.toLowerCase())).filter((st): st is OverviewState => !!st);
  const tab = (k: KpiListKind) => ({ href: tabHref(k), active: kind === k });
  const stateTile = (st: OverviewState, label: string, value: number | null, parts: KpiPart[]): KpiTileData => ({
    label: `${st.name} ${label}`,
    value,
    color: TONE.state,
    icon: MapPin,
    parts,
    href: stateHref(activeState === st.id ? undefined : st.id),
    active: activeState === st.id,
  });

  if (group === "hotoBlocks") {
    return (
      <KpiStrip
        label="HOTO block summary"
        overall={[
          { label: "Total Blocks", value: summary.blocks, color: TONE.total, icon: BoxSelect },
          { label: "HOTO Done Blocks", value: summary.hotoDoneBlocks, color: TONE.done, icon: CircleCheckBig, ...tab("hoto-blocks") },
          { label: "HOTO Pending Blocks", value: summary.hotoPendingBlocks, color: TONE.pending, icon: Clock, ...tab("hoto-pending-blocks") },
        ]}
        states={ordered.map((st) =>
          stateTile(st, "Blocks", st.blocks, [
            { label: "Done", value: st.hotoDoneBlocks, color: TONE.done },
            { label: "Pending", value: st.hotoPendingBlocks, color: TONE.pending },
          ]),
        )}
      />
    );
  }

  if (group === "hotoGps") {
    return (
      <KpiStrip
        label="HOTO GP summary"
        overall={[
          { label: "Total Existing GPs", value: summary.existingGps, color: TONE.total, icon: BoxSelect },
          { label: "HOTO Done GPs", value: summary.hotoDoneGps, color: TONE.done, icon: CircleCheckBig, ...tab("hoto-gps") },
          { label: "HOTO Pending GPs", value: summary.hotoPendingGps, color: TONE.pending, icon: Clock, ...tab("hoto-pending-gps") },
          { label: "Converted to NP / Closed", value: summary.convertedOrClosed, color: TONE.removed, icon: Ban, ...tab("removed-gps") },
        ]}
        states={ordered.map((st) =>
          stateTile(st, "GPs", st.existingGps, [
            { label: "Done", value: st.hotoDoneGps, color: TONE.done },
            { label: "Pending", value: st.hotoPendingGps, color: TONE.pending },
            { label: "NP / Closed", value: st.convertedOrClosed, color: TONE.removed },
          ]),
        )}
      />
    );
  }

  return (
    <KpiStrip
      label="AMC GP summary"
      overall={[
        { label: "Total Existing GPs", value: summary.existingGps, color: TONE.total, icon: BoxSelect },
        { label: "GPs in AMC at HOTO", value: summary.amcAtHotoGps, color: TONE.amcAtHoto, icon: ShieldCheck, ...tab("amc-original-gps") },
        { label: "Incremental GPs", value: summary.incrementalGps, color: TONE.incremental, icon: Wrench, ...tab("incremental-gps") },
        { label: "Non-AMC GPs", value: summary.nonAmcGps, color: TONE.nonAmc, icon: ShieldOff },
        { label: "Converted to NP / Closed", value: summary.convertedOrClosed, color: TONE.removed, icon: Ban },
      ]}
      states={ordered.map((st) =>
        stateTile(st, "GPs", st.existingGps, [
          { label: "AMC at HOTO", value: st.amcAtHotoGps, color: TONE.amcAtHoto },
          { label: "Incremental", value: st.incrementalGps, color: TONE.incremental },
          { label: "Non-AMC", value: st.nonAmcGps, color: TONE.nonAmc },
          { label: "NP / Closed", value: st.convertedOrClosed, color: TONE.removed },
        ]),
      )}
    />
  );
}

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
  const from = params.get("from");
  return <KpiList kind={kind} fromCircle={from === "circle"} fromAmc={from === "amc"} fromBlockParam={from === "block"} group={group && KPI_LIST_GROUPS[group].tabs.some((t) => t.kind === kind) ? group : null} />;
}

function KpiList({ kind, fromCircle, fromAmc, fromBlockParam, group }: { kind: KpiListKind; fromCircle: boolean; fromAmc: boolean; fromBlockParam: boolean; group: KpiListGroup | null }) {
  const { filters, period, navigate, hrefTo } = useFilters();
  const meta = useMeta();
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<KpiListSort | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [expandedBlocks, setExpandedBlocks] = useState<Set<string>>(() => new Set());

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
  // All-state KPI strip of the HOTO / AMC detail pages (not when the page was opened for one block from Block Insights).
  const strip = (group === "hotoBlocks" || group === "hotoGps" || group === "amcGps") && !(fromBlockParam && filters.block) ? group : null;
  const showSummary = strip != null;
  const summaryQuery = useApiQuery(
    showSummary && period ? `overview:${period.weekId}:${period.compareWeekId}` : null,
    () => api.getOverview({ weekId: period!.weekId, compareWeekId: period!.compareWeekId }),
  );
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
  // Lists opened from a Block Insights card go back to that block's summary (same week, same block).
  const fromBlock = fromBlockParam && !!filters.block;
  const blockName = meta?.blocks.find((b) => b.id === filters.block)?.name;
  const blockHref = summary(hrefTo("/dashboard/block-insights", { circle: filters.circle, district: filters.district, block: filters.block, gp: undefined }));
  const backHref = fromBlock ? blockHref : group ? statesHref : fromAmc ? amcHref : backToCircle ? circleHref : overviewHref;
  const backLabel = fromBlock
    ? `Back to ${blockName ?? "Block Insights"}`
    : groupView
      ? `Back to ${groupView.title}`
      : fromAmc
        ? "Back to AMC Conversion"
        : backToCircle
          ? `Back to ${stateName ?? "Circle Insights"}`
          : "Back to Circle Overview";
  // Title scope of a tabbed page: the block it was opened from, else the state (or all states).
  const scopeName = fromBlock ? `${blockName ?? "Block"} block` : (stateName ?? "All states");
  const isHoto = ["hoto-gps", "hoto-blocks", "hoto-pending-gps", "hoto-pending-blocks", "all-blocks", "non-amc-gps", "existing-gps", "new-gp-blocks", "removed-gps"].includes(kind) || (kind.startsWith("amc-") && kind !== "amc-original-gps"); // amc-original-gps shows MTD availability
  const tabHref = (k: KpiListKind) => stateDetailHref(hrefTo(KPI_LIST_PATH), group!, k, fromBlock ? "block" : "states");
  const insightsHref = hrefTo("/dashboard/circle-insights", { circle: filters.circle, district: undefined, block: undefined, gp: undefined });

  const from = d && d.total ? (d.page - 1) * d.pageSize + 1 : 0;
  const to = d ? Math.min(d.page * d.pageSize, d.total) : 0;

  return (
    <div className="space-y-5">
      {/* ---------------- Title bar ---------------- */}
      <TitleBar
        breadcrumbs={
          fromBlock
            ? [{ label: "Circle Overview", href: overviewHref }, { label: `${blockName ?? "Block"} block`, href: blockHref }, { label: group ? KPI_LIST_GROUPS[group].title : (d?.title ?? "GP list") }]
            : group
              ? [{ label: "Circle Overview", href: overviewHref }, { label: groupView!.title, href: statesHref }, { label: `${stateName ?? "All states"} – ${KPI_LIST_GROUPS[group].title}` }]
              : fromAmc
                ? [{ label: "AMC Conversion Plan vs Execution", href: amcHref }, { label: d?.title ?? "GP list" }]
                : [{ label: "Circle Overview", href: overviewHref }, ...(backToCircle ? [{ label: stateName ?? "Circle Insights", href: circleHref }] : []), { label: d?.title ?? "KPI list" }]
        }
        title={group ? `${scopeName} – ${KPI_LIST_GROUPS[group].title}` : fromBlock ? `${scopeName} – ${d?.title ?? "GP list"}` : (d?.title ?? "Loading list…")}
        period={d ? `Week ${d.week.number} · ${isHoto ? "as of" : "MTD up to"} ${formatDate(d.asOf)}` : undefined}
        note={
          d
            ? `${d.valueTotal != null ? `${formatCount(d.valueTotal)} new GPs in ${formatCount(d.total)} blocks` : `${formatCount(d.total)} ${noun}`}${fromBlock ? "" : stateName ? ` in ${stateName}` : ""}`
            : undefined
        }
        aside={
          <>
            <Link href={backHref} className={buttonVariants({ variant: "outline" })}>
              <ChevronLeft aria-hidden /> {backLabel}
            </Link>
            {group && filters.circle && (
              <Link href={insightsHref} className={buttonVariants({ variant: "outline" })}>
                Open Circle Insights <ChevronRight aria-hidden />
              </Link>
            )}
            <Button variant="primary" onClick={download} disabled={!d || busy || d.total === 0}>
              {busy ? <Loader2 className="animate-spin" /> : <Download />}
              {busy ? "Preparing Excel…" : "Download Excel"}
            </Button>
          </>
        }
        tabs={
          group && (
            <nav aria-label="Lists for this state" className="flex flex-wrap gap-1">
              {KPI_LIST_GROUPS[group].tabs.map((t) => (
                <Link
                  key={t.kind}
                  href={tabHref(t.kind)}
                  aria-current={t.kind === kind ? "page" : undefined}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
                    t.kind === kind ? "bg-primary-soft text-primary ring-1 ring-inset ring-primary/25" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  {t.label}
                </Link>
              ))}
            </nav>
          )
        }
      >
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
      </TitleBar>

      {strip &&
        (summaryQuery.error ? (
          <Card className="p-3">
            <ErrorState error={summaryQuery.error} onRetry={summaryQuery.reload} />
          </Card>
        ) : (
          <DetailKpiStrip
            group={strip}
            kind={kind}
            summary={summaryQuery.data?.summary}
            states={summaryQuery.data?.stateDetails ?? []}
            activeState={filters.circle}
            tabHref={tabHref}
            stateHref={(circle) => stateDetailHref(hrefTo(KPI_LIST_PATH, { circle, district: undefined, block: undefined, gp: undefined }), strip, kind, "states")}
          />
        ))}

      {kind === "all-blocks" && d?.blockSummary && <AllBlocksKpiStrip s={d.blockSummary} />}

      {d && <ViewHint>{d.rule}.</ViewHint>}

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
                  {d.items.map((row, i) => {
                    const expanded = kind === "hoto-blocks" && expandedBlocks.has(row.id);
                    return (
                      <Fragment key={row.id}>
                        <tr
                          tabIndex={0}
                          aria-label={`Open ${isBlock ? "Block" : "GP"} Insights for ${row.name}`}
                          onClick={() => open(row)}
                          onKeyDown={(e) => e.key === "Enter" && open(row)}
                          className="cursor-pointer border-b border-border/70 last:border-0 hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
                        >
                          <td className="px-3 py-2 text-right text-muted-foreground">{from + i}</td>
                          {ui.cols.map((c) => (
                            <td key={c.key} className={cn("px-3 py-2", c.numeric && "text-right")}>
                              {kind === "hoto-blocks" && c.key === "gpDetails" ? (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  aria-expanded={expanded}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setExpandedBlocks((current) => {
                                      const next = new Set(current);
                                      if (next.has(row.id)) next.delete(row.id);
                                      else next.add(row.id);
                                      return next;
                                    });
                                  }}
                                  onKeyDown={(e) => e.stopPropagation()}
                                >
                                  <ChevronDown className={cn("transition-transform", expanded && "rotate-180")} />
                                  {expanded ? "Hide GPs" : `Show ${formatCount(row.gpDetails?.length ?? 0)} GPs`}
                                </Button>
                              ) : c.render(row)}
                            </td>
                          ))}
                          <td className="px-3 py-2 text-right text-xs font-semibold text-primary">Open →</td>
                        </tr>
                        {expanded && row.gpDetails && (
                          <tr className="border-b border-border/70 bg-muted/30">
                            <td colSpan={ui.cols.length + 2} className="px-6 py-3">
                              <div className="overflow-x-auto">
                                <table className="w-full text-xs">
                                  <thead>
                                    <tr className="text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                                      <th className="px-2 py-1">GP</th>
                                      <th className="px-2 py-1">GP code</th>
                                      <th className="px-2 py-1">HOTO Done Date</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {row.gpDetails.map((gp) => (
                                      <tr key={gp.id} className="border-t border-border/50">
                                        <td className="px-2 py-1.5 font-medium">{gp.name}</td>
                                        <td className="px-2 py-1.5 text-muted-foreground">{gp.code}</td>
                                        <td className="px-2 py-1.5">{date(gp.hotoDate)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
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
