"use client";

import { Cable, Network, UserCog, Users } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { TableSkeleton } from "@/components/feedback/states";
import { BlockFilter, CircleFilter, DistrictFilter } from "@/components/filters/filter-bar";
import { TitleBar, ViewHint } from "@/components/layout/page-header";
import { useMeta } from "@/components/providers/data-provider";
import { StatCard, type StatBreakdown } from "@/components/kpi/stat-card";
import { Segmented } from "@/components/ui/controls";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { api, type FieldQuery, type FieldRole, type FieldStateSummary } from "@/lib/api";
import { FIELD_PATH, FIELD_VIEWS, fieldViewFrom, type FieldViewId } from "@/lib/field-views";
import { cn } from "@/lib/utils/cn";
import { formatCount, formatDate, formatPercent } from "@/lib/utils/format";
import { BODY_ROW, HEAD_ROW, RowHead, TableCard, Td, Th } from "@/features/amc-conversion/table-ui";
import { ChainCell, FieldError, MaskNote, Pager, SearchBox, step } from "./field-parts";
import { TeamDirectory } from "./team-directory";

const STATE_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-7)"];
const avail = (v: number | null) => (v == null ? "NA" : formatPercent(v, 1));

/**
 * Field Team & Escalation – from the active Escalation Matrix upload, joined to the master data by GP code.
 * One view at a time (?view=, sidebar sub-menu); state / district / block are the shared filters.
 */
export function FieldTeamView() {
  const params = useSearchParams();
  const meta = useMeta();
  const { filters, hrefTo } = useFilters();
  const view = FIELD_VIEWS.find((v) => v.id === fieldViewFrom(params.get("view")))!;
  const stateName = meta?.circles.find((c) => c.id === filters.circle)?.name;
  const located = view.id === "lookup" || view.id === "down" || view.id === "gaps";
  const base = hrefTo(FIELD_PATH, { circle: undefined, district: undefined, block: undefined, gp: undefined });
  const pageHref = `${base}${base.includes("?") ? "&" : "?"}view=${view.id}`;
  return (
    <div className="space-y-5">
      <TitleBar
        breadcrumbs={[
          { label: "Circle Overview", href: hrefTo("/dashboard", { circle: undefined, district: undefined, block: undefined, gp: undefined }) },
          stateName ? { label: "Field Team & Escalation", href: pageHref } : { label: "Field Team & Escalation" },
          ...(stateName ? [{ label: stateName }] : []),
        ]}
        title={stateName ?? "Field Team & Escalation"}
        view={view.title}
        note={stateName ? "Field team of this state" : "All states – select a state to see only its team."}
      >
        <CircleFilter className="sm:w-full" />
        {located && <DistrictFilter className="sm:w-full" />}
        {located && <BlockFilter className="sm:w-full" />}
      </TitleBar>
      <div key={view.id} className="view-in space-y-5">
        <ViewHint>{view.hint}</ViewHint>
        <ViewBody id={view.id} />
      </div>
    </div>
  );
}

function ViewBody({ id }: { id: FieldViewId }) {
  if (id === "team") return <TeamDirectory />;
  if (id === "lookup") return <LookupView />;
  if (id === "workload") return <WorkloadView />;
  if (id === "down") return <DownView />;
  if (id === "gaps") return <GapsView />;
  return <SummaryView />;
}

/** Shared query (week + location filters) for the paged views; page resets when the scope changes. */
function useScope(search: string) {
  const { filters, period } = useFilters();
  const [page, setPage] = useState(1);
  const scope = `${period?.weekId}|${filters.circle}|${filters.district}|${filters.block}|${search}`;
  const [last, setLast] = useState(scope);
  if (scope !== last) {
    setLast(scope);
    setPage(1);
  }
  const q: FieldQuery | null = period ? { weekId: period.weekId, circleId: filters.circle, districtId: filters.district, blockId: filters.block, search: search || undefined, page } : null;
  return { q, key: `${scope}|${page}`, page, setPage };
}

function Source({ fileName, importedAt, asOf, week }: { fileName: string; importedAt: string | null; asOf?: string; week?: string }) {
  return (
    <p className="text-sm text-muted-foreground">
      Source: <b className="text-foreground">{fileName}</b>
      {importedAt && ` (uploaded ${formatDate(importedAt)})`}
      {asOf && ` · availability ${week ? `${week}, ` : ""}MTD up to ${formatDate(asOf)}`}
    </p>
  );
}

/* ------------------------------------------------------------------ 1. Summary */

function SummaryView() {
  const { period, filters, hrefTo } = useFilters();
  const q = useApiQuery(period ? `field-summary:${period.weekId}` : null, () => api.getFieldSummary(period!.weekId));
  const r = q.data ?? q.staleData;
  if (q.error) return <FieldError error={q.error} onRetry={q.reload} />;
  const circle = filters.circle;
  const t = r ? (circle ? (r.states.find((s) => s.id === circle) ?? r.total) : r.total) : undefined;
  const rows = circle ? [] : (r?.states ?? []);
  const by = (pick: (s: FieldStateSummary) => number): StatBreakdown[] => rows.map((s, i) => ({ label: s.name, value: pick(s), color: STATE_COLORS[i % STATE_COLORS.length] }));
  const viewHref = (v: FieldViewId, extra = "") => {
    const b = hrefTo(FIELD_PATH);
    return `${b}${b.includes("?") ? "&" : "?"}view=${v}${extra}`;
  };
  const teamHref = (role: FieldRole) => viewHref("team", `&role=${role}`);
  const L = !r;
  return (
    <div className="space-y-5">
      {r && <Source fileName={r.source.fileName} importedAt={r.source.importedAt} asOf={r.asOf} week={r.week.label} />}
      <section aria-label="Field team" className="space-y-2.5">
        <h2 className="text-[13px] font-extrabold uppercase tracking-[0.08em] text-subheading">Field team – each person counted once</h2>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <StatCard
            compact
            loading={L}
            layout="split"
            icon={UserCog}
            tone="var(--series-1)"
            label="Area managers"
            info="Distinct area managers in the Escalation Matrix (same state + same name counted once). “Vacant” entries are open posts and are not counted."
            value={formatCount(t?.ams)}
            unit="AMs"
            caption={
              t ? (
                <>
                  {t.amVacantPosts > 0 && <span className="block">+ {formatCount(t.amVacantPosts)} vacant posts ({formatCount(t.amVacantGps)} GPs)</span>}
                  <span className="block">{formatCount(t.missingAm)} GPs without an AM</span>
                </>
              ) : undefined
            }
            breakdown={rows.length ? by((s) => s.ams) : undefined}
            href={teamHref("am")}
            linkLabel="View area managers"
          />
          <StatCard
            compact
            loading={L}
            layout="split"
            icon={Cable}
            tone="var(--series-2)"
            label="Splicers"
            info="Distinct splicers – spellings of one name in the same state (e.g. OMPRAKASH / Om Prakash) are counted once."
            value={formatCount(t?.splicers)}
            unit="splicers"
            caption={
              t ? (
                <>
                  <span className="block">{formatCount(t.gpsPerSplicer ?? null)} GPs per splicer</span>
                  <span className="block">{formatCount(t.missingSplicer)} GPs without a splicer</span>
                </>
              ) : undefined
            }
            breakdown={rows.length ? by((s) => s.splicers) : undefined}
            href={teamHref("splicer")}
            linkLabel="View splicers"
          />
          <StatCard
            compact
            loading={L}
            layout="split"
            icon={Network}
            tone="var(--series-3)"
            label="FRT teams"
            info="Distinct FRT codes in the Escalation Matrix."
            value={formatCount(t?.frtTeams)}
            unit="teams"
            caption={t ? `${formatCount(t.missingFrt)} GPs without an FRT team` : undefined}
            breakdown={rows.length ? by((s) => s.frtTeams) : undefined}
            href={teamHref("frt")}
            linkLabel="View FRT teams"
          />
          <StatCard
            compact
            loading={L}
            layout="split"
            icon={Users}
            tone="var(--series-7)"
            label="Field engineers"
            info="Distinct field engineers (same state + same name counted once)."
            value={formatCount(t?.fes)}
            unit="FEs"
            caption={t ? `${formatCount(t.gpsPerFe ?? null)} GPs per FE` : undefined}
            breakdown={rows.length ? by((s) => s.fes) : undefined}
            href={teamHref("fe")}
            linkLabel="View FEs"
          />
        </div>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ 2. Escalation lookup */

const CHAIN_COLS = [
  ["frt", "FRT"],
  ["splicer", "Splicer"],
  ["fe", "FE"],
  ["am", "AM"],
  ["shq", "SHQ SPOC"],
  ["coh", "COH"],
  ["cbh", "CBH"],
] as const;

function LookupView() {
  const [search, setSearch] = useState("");
  const { q, key, setPage } = useScope(search);
  const res = useApiQuery(q ? `field-lookup:${key}` : null, () => api.getFieldLookup(q!));
  const d = res.data ?? res.staleData;
  if (res.error) return <FieldError error={res.error} onRetry={res.reload} />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SearchBox onSearch={setSearch} placeholder="GP, block, FRT code or a person's name" />
      </div>
      {d && <Source fileName={d.source.fileName} importedAt={d.source.importedAt} />}
      <MaskNote masked={d?.phonesMasked} />
      {!d ? (
        <Card className="p-4">
          <TableSkeleton rows={8} />
        </Card>
      ) : (
        <TableCard title="Escalation chain by GP" description={`${formatCount(d.total)} GPs · call in this order: FRT → Splicer → FE → AM → SHQ SPOC → COH → CBH`}>
          <div className={cn("overflow-x-auto rounded-lg border border-border", res.loading && "opacity-60")}>
            <table className="w-full min-w-[1150px] text-[13px]">
              <caption className="sr-only">Escalation chain by GP</caption>
              <thead>
                <tr className={HEAD_ROW}>
                  <Th first>GP</Th>
                  {CHAIN_COLS.map(([k, label], i) => (
                    <Th key={k} group={i === 0} className="text-left">
                      {i + 1}. {label}
                    </Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.items.map((g) => (
                  <tr key={g.id} className={cn(BODY_ROW, "align-top")}>
                    <RowHead>
                      <span className="block max-w-[180px] truncate" title={g.name}>
                        {g.name}
                      </span>
                      <span className="block text-[11px] font-normal text-muted-foreground">
                        {g.code} · {g.block}, {g.district}
                      </span>
                    </RowHead>
                    {CHAIN_COLS.map(([k], i) => (
                      <Td key={k} group={i === 0} className="whitespace-normal text-left">
                        <ChainCell step={step(g.chain, k)} compact />
                      </Td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={d.page} pages={d.pages} total={d.total} pageSize={d.pageSize} onPage={setPage} busy={res.loading} />
        </TableCard>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ 3. Team workload */

const ROLES: { value: FieldRole; label: string }[] = [
  { value: "fe", label: "FE" },
  { value: "splicer", label: "Splicer" },
  { value: "frt", label: "FRT team" },
  { value: "am", label: "AM" },
];

function WorkloadView() {
  const { period, filters } = useFilters();
  const [role, setRole] = useState<FieldRole>("fe");
  const q = useApiQuery(period ? `field-workload:${role}:${period.weekId}:${filters.circle}` : null, () => api.getFieldWorkload(role, { weekId: period!.weekId, circleId: filters.circle }));
  const d = q.data ?? q.staleData;
  if (q.error) return <FieldError error={q.error} onRetry={q.reload} />;
  const roleLabel = ROLES.find((x) => x.value === role)!.label;
  return (
    <div className="space-y-4">
      {d && <Source fileName={d.source.fileName} importedAt={d.source.importedAt} asOf={d.asOf} week={d.week.label} />}
      <MaskNote masked={d?.phonesMasked && role !== "frt"} />
      {!d ? (
        <Card className="p-4">
          <TableSkeleton rows={8} />
        </Card>
      ) : (
        <TableCard
          title={`${d.roleLabel} workload`}
          description={`${formatCount(d.people)} ${roleLabel === "FRT team" ? "teams" : "people"} · ${formatCount(d.avgGps ?? null)} GPs on average, up to ${formatCount(d.maxGps ?? null)}${d.unassignedGps ? ` · ${formatCount(d.unassignedGps)} GPs without a ${roleLabel}` : ""}`}
          actions={<Segmented<FieldRole> ariaLabel="Role" value={role} onChange={setRole} options={ROLES} />}
        >
          <div className={cn("max-h-[640px] overflow-auto rounded-lg border border-border", q.loading && "opacity-60")}>
            <table className="w-full min-w-[860px] text-[13px]">
              <caption className="sr-only">{d.roleLabel} workload</caption>
              <thead className="sticky top-0 z-20">
                <tr className={HEAD_ROW}>
                  <Th first>{roleLabel}</Th>
                  <Th className="text-left">State</Th>
                  {role !== "frt" && <Th className="text-left">Phone</Th>}
                  <Th group>GPs</Th>
                  <Th>Blocks</Th>
                  <Th>AMC GPs</Th>
                  <Th group>Availability (MTD)</Th>
                  <Th>GPs at 0%</Th>
                  <Th>GPs &lt;90%</Th>
                </tr>
              </thead>
              <tbody className="tabular">
                {d.items.map((x) => (
                  <tr key={x.id} className={BODY_ROW}>
                    <RowHead>{x.name}</RowHead>
                    <Td className="text-left">{x.circle}</Td>
                    {role !== "frt" && (
                      <Td className="text-left text-xs text-muted-foreground">
                        {x.phone ?? "—"}
                        {x.numbers > 1 && <span className="ml-1 text-warning-text">({x.numbers} numbers)</span>}
                      </Td>
                    )}
                    <Td group className="font-semibold">
                      {formatCount(x.gps)}
                    </Td>
                    <Td>{formatCount(x.blocks)}</Td>
                    <Td>{formatCount(x.amcGps)}</Td>
                    <Td group>{avail(x.availability)}</Td>
                    <Td className={cn(x.gpsAtZero > 0 && "font-medium text-critical-text")}>{formatCount(x.gpsAtZero)}</Td>
                    <Td>{formatCount(x.gpsBelow90)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </TableCard>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ 4. Down GPs – who to call */

function DownView() {
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<"zero" | "below90">("zero");
  const { q, key, setPage } = useScope(`${search}|${mode}`);
  const res = useApiQuery(q ? `field-down:${key}` : null, () => api.getFieldDown(mode, { ...q!, search: search || undefined }));
  const d = res.data ?? res.staleData;
  if (res.error) return <FieldError error={res.error} onRetry={res.reload} />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <SearchBox onSearch={setSearch} placeholder="GP, block, FRT code or a person's name" />
      </div>
      {d && <Source fileName={d.source.fileName} importedAt={d.source.importedAt} asOf={d.asOf} week={d.week.label} />}
      <MaskNote masked={d?.phonesMasked} />
      {!d ? (
        <Card className="p-4">
          <TableSkeleton rows={8} />
        </Card>
      ) : (
        <TableCard
          title={mode === "zero" ? "AMC GPs at 0% – who to call" : "AMC GPs below 90% – who to call"}
          description={`${formatCount(d.total)} GPs · lowest availability first${d.withoutSplicer ? ` · ${formatCount(d.withoutSplicer)} without a splicer` : ""}`}
          actions={
            <Segmented<"zero" | "below90">
              ariaLabel="Which GPs"
              value={mode}
              onChange={setMode}
              options={[
                { value: "zero", label: "0% MTD" },
                { value: "below90", label: "Below 90%" },
              ]}
            />
          }
        >
          <div className={cn("overflow-x-auto rounded-lg border border-border", res.loading && "opacity-60")}>
            <table className="w-full min-w-[1000px] text-[13px]">
              <caption className="sr-only">Down GPs with their field team</caption>
              <thead>
                <tr className={HEAD_ROW}>
                  <Th first>GP</Th>
                  <Th>MTD %</Th>
                  {CHAIN_COLS.slice(0, 4).map(([k, label], i) => (
                    <Th key={k} group={i === 0} className="text-left">
                      {i + 1}. {label}
                    </Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.items.map((g) => (
                  <tr key={g.id} className={cn(BODY_ROW, "align-top", g.noSplicer && "bg-critical-soft/30")}>
                    <RowHead>
                      <span className="block max-w-[200px] truncate" title={g.name}>
                        {g.name}
                      </span>
                      <span className="block text-[11px] font-normal text-muted-foreground">
                        {g.code} · {g.block}, {g.circle}
                      </span>
                    </RowHead>
                    <Td className="font-semibold text-critical-text">{avail(g.availability)}</Td>
                    {CHAIN_COLS.slice(0, 4).map(([k], i) => (
                      <Td key={k} group={i === 0} className="whitespace-normal text-left">
                        <ChainCell step={step(g.chain, k)} />
                      </Td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager page={d.page} pages={d.pages} total={d.total} pageSize={d.pageSize} onPage={setPage} busy={res.loading} />
        </TableCard>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ 5. Data gaps */

function GapsView() {
  const params = useSearchParams();
  const [issue, setIssue] = useState<string | null>(params.get("issue"));
  const [search, setSearch] = useState("");
  const { q, key, setPage } = useScope(`${search}|${issue}`);
  const res = useApiQuery(q ? `field-gaps:${key}` : null, () => api.getFieldGaps(issue, { ...q!, search: search || undefined }));
  const d = res.data ?? res.staleData;
  if (res.error) return <FieldError error={res.error} onRetry={res.reload} />;
  const active = d?.issues.find((i) => i.id === issue);
  return (
    <div className="space-y-4">
      {d && <Source fileName={d.source.fileName} importedAt={d.source.importedAt} />}
      {!d ? (
        <Card className="p-4">
          <TableSkeleton rows={8} />
        </Card>
      ) : (
        <>
          <TableCard title="Gaps in the Escalation Matrix" description="Click a row to list its GPs">
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[640px] text-[13px]">
                <caption className="sr-only">Gaps in the Escalation Matrix by state</caption>
                <thead>
                  <tr className={HEAD_ROW}>
                    <Th first>Gap</Th>
                    {d.states.map((s, i) => (
                      <Th key={s.id} group={i === 0}>
                        {s.name}
                      </Th>
                    ))}
                    <Th group>Total GPs</Th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {d.issues.map((i) => (
                    <tr
                      key={i.id}
                      tabIndex={0}
                      aria-label={`List GPs: ${i.label}`}
                      onClick={() => setIssue(i.id)}
                      onKeyDown={(e) => e.key === "Enter" && setIssue(i.id)}
                      className={cn(BODY_ROW, "cursor-pointer", issue === i.id && "bg-primary-soft/40")}
                    >
                      <RowHead>{i.label}</RowHead>
                      {d.states.map((s, k) => (
                        <Td key={s.id} group={k === 0} className={cn(i.counts[s.id] > 0 ? "text-foreground" : "text-subtle-foreground")}>
                          {formatCount(i.counts[s.id] ?? 0)}
                        </Td>
                      ))}
                      <Td group className={cn("font-semibold", i.total === 0 && "font-normal text-subtle-foreground")}>
                        {formatCount(i.total)}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </TableCard>

          {active && d.items && (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <SearchBox onSearch={setSearch} placeholder="GP, block, FRT code or a person's name" />
              </div>
              <MaskNote masked={d.phonesMasked} />
              <TableCard title={active.label} description={`${formatCount(d.total ?? 0)} GPs`}>
                <div className={cn("overflow-x-auto rounded-lg border border-border", res.loading && "opacity-60")}>
                  <table className="w-full min-w-[1000px] text-[13px]">
                    <caption className="sr-only">{active.label}</caption>
                    <thead>
                      <tr className={HEAD_ROW}>
                        <Th first>GP</Th>
                        {issue === "am-differs" && <Th className="text-left">AM in master data</Th>}
                        {CHAIN_COLS.slice(0, 4).map(([k, label], i) => (
                          <Th key={k} group={i === 0} className="text-left">
                            {label}
                          </Th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {d.items.map((g) => (
                        <tr key={g.id} className={cn(BODY_ROW, "align-top")}>
                          <RowHead>
                            <span className="block max-w-[200px] truncate" title={g.name}>
                              {g.name}
                            </span>
                            <span className="block text-[11px] font-normal text-muted-foreground">
                              {g.code} · {g.block}, {g.circle}
                            </span>
                          </RowHead>
                          {issue === "am-differs" && <Td className="text-left font-medium">{g.masterAm ?? "—"}</Td>}
                          {CHAIN_COLS.slice(0, 4).map(([k], i) => (
                            <Td key={k} group={i === 0} className="whitespace-normal text-left">
                              <ChainCell step={step(g.chain, k)} />
                            </Td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pager page={d.page ?? 1} pages={d.pages ?? 1} total={d.total ?? 0} pageSize={d.pageSize ?? 50} onPage={setPage} busy={res.loading} />
              </TableCard>
            </>
          )}
        </>
      )}
    </div>
  );
}
