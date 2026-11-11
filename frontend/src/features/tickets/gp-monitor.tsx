"use client";

import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Eye, FileCheck2, ListX, MailCheck, RotateCcw, Search, Wrench, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/feedback/states";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { MiniKpi } from "@/components/kpi/mini-kpi";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { ticketApi, type GpCategory, type GpMonitorFilters, type GpMonitorKpis, type GpMonitorRow, type GpMonitorSort } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";
import { CATEGORY, GP_CATEGORIES, GpCategoryBadge } from "./gp-category";
import { TicketStatusBadge, ticketDay, ticketTime } from "./ticket-parts";
import { GpStatusBadge, ProofList } from "./ticket-proof";

const pct = (n: number, of: number) => (of ? `${((n / of) * 100).toFixed(1)}%` : "NA");
const wk = (w: string) => w.replace("W-", "Week ");
const ICON: Record<GpCategory, React.ComponentType<{ className?: string }>> = { A: Wrench, B: FileCheck2, C: RotateCcw, D: XCircle, E: MailCheck };

/** `?gps=a` … `?gps=e` of the Admin Tickets page -> category */
export const categoryFrom = (v: string | null): GpCategory | null => {
  const c = (v ?? "").toUpperCase();
  return c in CATEGORY ? (c as GpCategory) : null;
};

/**
 * The five category KPIs of the GP-wise task tickets: each GP once, counted under its CURRENT category (latest chosen
 * by the Area Manager / FE in any of its tickets; backend app/tickets/monitor.py). `hrefFor` = tiles open the GP list
 * of that category; `active` = the list shown (tiles act as tabs there).
 */
export function CategoryKpiCards({ k, loading, hrefFor, active }: { k?: GpMonitorKpis; loading: boolean; hrefFor: (c: GpCategory) => string | undefined; active?: GpCategory }) {
  const total = k?.total ?? 0;
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {GP_CATEGORIES.map((c) => {
          const n = k?.categories?.[c.code] ?? 0;
          const docs = k?.categoryWithDocument?.[c.code] ?? 0;
          return (
            <MiniKpi
              key={c.code}
              loading={loading}
              icon={ICON[c.code]}
              tone={c.color}
              label={c.label}
              info={`${c.info} GPs of the GP-wise task tickets whose current status is "${c.label}" – each GP once (a changed status moves it to the new category). Click to see the GPs with Area Manager, FE, Block and documents.`}
              value={formatCount(n)}
              unit="GPs"
              caption={k ? `${pct(n, total)} of ${formatCount(total)} · ${formatCount(docs)} with document` : undefined}
              href={hrefFor(c.code)}
              active={active === c.code}
            />
          );
        })}
      </div>
      {k && (
        <p className="text-[0.71875rem] text-muted-foreground">
          {formatCount(total)} assigned GPs · {formatCount(k.notClassified)} not classified yet · each GP counted once across all tickets
        </p>
      )}
    </div>
  );
}

const EMPTY: GpMonitorFilters = {};

/** GPs of one category with filters, search, sorting, pagination and the GP detail. */
export function GpMonitorView({ category, hrefFor }: { category: GpCategory; hrefFor: (c: GpCategory) => string }) {
  const [f, setF] = useState<GpMonitorFilters>(EMPTY);
  const [sort, setSort] = useState<{ key: GpMonitorSort; desc: boolean }>({ key: "date", desc: true });
  const [pg, setPg] = useState({ category, page: 1 });
  const page = pg.category === category ? pg.page : 1; // a new tab starts on page 1
  const setPage = (n: number) => setPg({ category, page: n });
  const [open, setOpen] = useState<string | null>(null);
  const q = { ...f, category, sort: sort.key, desc: sort.desc, page, pageSize: 25 };
  const list = useApiQuery(`gp-monitor:${JSON.stringify(q)}`, () => ticketApi.listGpMonitor(q));
  const data = list.data ?? list.staleData;
  const set = (patch: Partial<GpMonitorFilters>) => {
    setF((cur) => {
      const next = { ...cur, ...patch };
      if ("circle" in patch) next.areaManager = next.fe = next.block = next.ticket = undefined; // dependent filters
      if ("areaManager" in patch) next.fe = next.block = next.ticket = undefined;
      return next;
    });
    setPage(1);
  };
  const active = Object.values(f).some(Boolean);
  const c = CATEGORY[category];

  return (
    <div className="space-y-5">
      <CategoryKpiCards k={data?.kpis} loading={!data} active={category} hrefFor={(x) => (x === category ? undefined : hrefFor(x))} />
      <Card className="overflow-hidden p-0">
        <div className="flex flex-col gap-1 border-b border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="flex items-center gap-2 text-base font-bold text-subheading">
              <span className="size-2.5 rounded-full" style={{ background: c.color }} aria-hidden /> {c.label} – GP details
            </h3>
            <p className="text-[0.78125rem] text-muted-foreground">
              Each GP once with its current status · Area Manager, FE and Block from the ticket where the status was chosen (Escalation Matrix + master data) · documents exactly as uploaded
            </p>
          </div>
        </div>
        <MonitorFilters f={f} set={set} clear={() => (setF(EMPTY), setPage(1))} active={active} options={data?.options} />
        <FeWise f={f} onPick={(am, fe) => set({ ...(f.areaManager === am ? {} : { areaManager: am }), fe })} />
        {list.error ? (
          <ErrorState error={list.error} onRetry={list.reload} />
        ) : !data ? (
          <div className="p-4">
            <TableSkeleton rows={8} />
          </div>
        ) : data.total === 0 ? (
          <EmptyState icon={ListX} title={active ? `No "${c.label}" GPs match the filters` : `No GP is marked "${c.label}" yet`} description={active ? "Change or clear the filters." : "GPs appear here once the Area Manager / FE chooses this status in a ticket."} />
        ) : (
          <>
            <div className={cn("max-h-[38.75rem] overflow-auto", list.loading && "opacity-60 transition-opacity")}>
              <table className="w-full min-w-[86.25rem] text-[0.8125rem]">
                <caption className="sr-only">{c.label} GPs</caption>
                <thead className="sticky top-0 z-10">
                  <tr className="border-b border-border bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                    {(
                      [
                        ["gpName", "GP Name"],
                        ["block", "Block"],
                        ["fe", "FE Name"],
                        ["areaManager", "Area Manager"],
                        ["circle", "Circle"],
                        [null, "Selected Status"],
                        [null, "Document Status"],
                        [null, "Document"],
                        ["ticket", "Ticket Details"],
                        ["date", "Status Updated"],
                        [null, "Remarks"],
                        [null, "Action"],
                      ] as [GpMonitorSort | null, string][]
                    ).map(([key, label]) => (
                      <th key={label} scope="col" className={cn("px-3 py-2", label === "Action" && "text-right")} aria-sort={key && sort.key === key ? (sort.desc ? "descending" : "ascending") : undefined}>
                        {key ? (
                          <button type="button" className="inline-flex items-center gap-1 uppercase hover:text-foreground" onClick={() => (setSort((s) => ({ key, desc: s.key === key ? !s.desc : key === "date" })), setPage(1))}>
                            {label}
                            {sort.key === key && (sort.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
                          </button>
                        ) : (
                          label
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="tabular">
                  {data.items.map((r) => (
                    <tr key={r.gpCode} className="border-b border-border/70 align-top last:border-0 hover:bg-accent/40">
                      <td className="px-3 py-2">
                        <span className="font-medium">{r.gpName}</span>
                        <span className="block text-[0.71875rem] font-semibold text-primary">{r.gpCode}</span>
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">{r.block ?? "—"}</td>
                      <td className={cn("px-3 py-2", !r.fieldEngineer && "text-warning-text")}>{r.fieldEngineer ?? "Not mapped"}</td>
                      <td className="px-3 py-2 font-medium">{r.areaManager}</td>
                      <td className="px-3 py-2 text-muted-foreground">{r.circle}</td>
                      <td className="px-3 py-2">
                        <GpCategoryBadge code={r.gpCategory} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        {r.files.length ? (
                          <span className="inline-flex rounded-full bg-good-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-good-text">Attached ({r.files.length})</span>
                        ) : (
                          <span className="inline-flex rounded-full bg-warning-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-warning-text">Not Attached</span>
                        )}
                      </td>
                      <td className="min-w-[11.25rem] max-w-[14.375rem] px-3 py-2">
                        <ProofList files={r.files} compact emptyText="—" />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-[0.75rem]">
                        <span className="font-semibold">{r.categoryTicket ?? r.ticket}</span> <TicketStatusBadge status={r.ticketStatus} />
                        <span className="block text-muted-foreground">
                          {wk(r.week)} · {r.kind === "WEEK" ? "this week" : "pending"}
                          {r.tickets.length > 1 && ` · in ${r.tickets.length} tickets`}
                        </span>
                        <span className="block text-muted-foreground">
                          Achieved {r.achieved}/{r.target}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-[0.75rem]">{r.categoryAt ? ticketTime(r.categoryAt) : "—"}</td>
                      <td className="max-w-[13.75rem] px-3 py-2 text-[0.78125rem]">{r.remarks ? <span className="line-clamp-3">{r.remarks}</span> : <span className="text-muted-foreground">No Remarks</span>}</td>
                      <td className="px-3 py-2 text-right">
                        <Button size="sm" variant="ghost" onClick={() => setOpen(r.gpCode)}>
                          <Eye /> View Details
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={data.page} pageSize={data.pageSize} total={data.total} loading={list.loading} onPage={setPage} />
          </>
        )}
      </Card>
      <GpDetailDialog gpCode={open} onClose={() => setOpen(null)} />
    </div>
  );
}

/** FE-wise category split of the filtered GPs (each GP once); a row filters the table to that Field Engineer. */
function FeWise({ f, onPick }: { f: GpMonitorFilters; onPick: (am: string, fe: string) => void }) {
  const [open, setOpen] = useState(false);
  const q = useApiQuery(open ? `gp-monitor-fe:${JSON.stringify(f)}` : null, () => ticketApi.getGpMonitorSummary(f, "category"));
  const rows = (q.data ?? q.staleData)?.byFe ?? [];
  return (
    <div className="border-b border-border">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left text-[0.8125rem] font-semibold">
        Field Engineer-wise status <span className="text-[0.75rem] font-normal text-muted-foreground">{open ? "Hide" : "Show"} – GPs per category and FE for the filters above</span>
      </button>
      {open && (
        <div className="max-h-[20rem] overflow-auto px-4 pb-3">
          {q.error ? (
            <ErrorState error={q.error} onRetry={q.reload} />
          ) : !q.data && !q.staleData ? (
            <TableSkeleton rows={4} />
          ) : rows.length === 0 ? (
            <p className="py-2 text-[0.78125rem] text-muted-foreground">No GPs match the filters.</p>
          ) : (
            <table className="w-full min-w-[61.25rem] text-[0.78125rem]">
              <thead className="sticky top-0 bg-card">
                <tr className="text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="px-2 py-1.5">Area Manager</th>
                  <th scope="col" className="px-2 py-1.5">Field Engineer</th>
                  <th scope="col" className="px-2 py-1.5 text-right">GPs</th>
                  {GP_CATEGORIES.map((c) => (
                    <th key={c.code} scope="col" className="px-2 py-1.5 text-right" title={c.label}>
                      <span className="inline-flex items-center gap-1">
                        <span className="size-1.5 rounded-full" style={{ background: c.color }} aria-hidden />
                        {c.label}
                      </span>
                    </th>
                  ))}
                  <th scope="col" className="px-2 py-1.5 text-right">Not classified</th>
                  <th scope="col" className="px-2 py-1.5 text-right">Without document</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {rows.map((r) => (
                  <tr key={`${r.areaManager}|${r.fieldEngineer}`} className="border-t border-border/60">
                    <td className="px-2 py-1.5">{r.areaManager}</td>
                    <td className="px-2 py-1.5">
                      <button type="button" className={cn("font-semibold hover:underline", r.mapped ? "text-primary" : "text-warning-text")} onClick={() => onPick(r.areaManager, r.fieldEngineer)} title="Show only this Field Engineer's GPs">
                        {r.fieldEngineer}
                      </button>
                    </td>
                    <td className="px-2 py-1.5 text-right">{r.total}</td>
                    {GP_CATEGORIES.map((c) => (
                      <td key={c.code} className="px-2 py-1.5 text-right font-semibold" style={r.categories?.[c.code] ? { color: c.color } : undefined}>
                        {r.categories?.[c.code] ?? 0}
                      </td>
                    ))}
                    <td className="px-2 py-1.5 text-right text-muted-foreground">{r.notClassified ?? 0}</td>
                    <td className="px-2 py-1.5 text-right">{r.withoutProof}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function MonitorFilters({
  f,
  set,
  clear,
  active,
  options,
}: {
  f: GpMonitorFilters;
  set: (p: Partial<GpMonitorFilters>) => void;
  clear: () => void;
  active: boolean;
  options?: { circles: string[]; areaManagers: string[]; fieldEngineers?: string[]; blocks: string[]; weeks: string[]; tickets: string[] };
}) {
  const o = options ?? { circles: [], areaManagers: [], blocks: [], weeks: [], tickets: [] };
  const opt = (xs: string[], label?: (x: string) => string) => xs.map((x) => ({ value: x, label: label ? label(x) : x }));
  return (
    <div className="space-y-3 border-b border-border px-4 py-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <SearchableSelect label="Circle" value={f.circle} onChange={(v) => set({ circle: v })} options={opt(o.circles)} allowClear clearLabel="All circles" placeholder="All circles" />
        <SearchableSelect label="Area Manager" value={f.areaManager} onChange={(v) => set({ areaManager: v })} options={opt(o.areaManagers)} allowClear clearLabel="All Area Managers" placeholder="All Area Managers" />
        <SearchableSelect label="Field Engineer" value={f.fe} onChange={(v) => set({ fe: v })} options={opt(o.fieldEngineers ?? [])} allowClear clearLabel="All Field Engineers" placeholder="All Field Engineers" />
        <SearchableSelect label="Block" value={f.block} onChange={(v) => set({ block: v })} options={opt(o.blocks)} allowClear clearLabel="All blocks" placeholder="All blocks" />
        <SearchableSelect label="Week" value={f.week} onChange={(v) => set({ week: v })} options={opt(o.weeks, wk)} allowClear clearLabel="All weeks" placeholder="All weeks" />
        <SearchableSelect label="Ticket ID" value={f.ticket} onChange={(v) => set({ ticket: v })} options={opt(o.tickets)} allowClear clearLabel="All tickets" placeholder="All tickets" />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(3,minmax(0,1fr))_repeat(2,minmax(0,0.8fr))_auto]">
        <DebouncedInput label="Search" icon value={f.search ?? ""} onChange={(v) => set({ search: v || undefined })} placeholder="GP, block, AM, FE, ticket, remark" />
        <DebouncedInput label="GP Code" value={f.gpCode ?? ""} onChange={(v) => set({ gpCode: v || undefined })} placeholder="e.g. 35520" />
        <DebouncedInput label="GP Name" value={f.gpName ?? ""} onChange={(v) => set({ gpName: v || undefined })} placeholder="e.g. Khera Thakur" />
        <label className="flex min-w-0 flex-col gap-1">
          <span className="text-xs font-semibold text-foreground/75">Status updated from</span>
          <Input type="date" value={f.dateFrom ?? ""} max={f.dateTo || undefined} onChange={(e) => set({ dateFrom: e.target.value || undefined })} />
        </label>
        <label className="flex min-w-0 flex-col gap-1">
          <span className="text-xs font-semibold text-foreground/75">Status updated to</span>
          <Input type="date" value={f.dateTo ?? ""} min={f.dateFrom || undefined} onChange={(e) => set({ dateTo: e.target.value || undefined })} />
        </label>
        <div className="flex items-end">
          <Button variant="ghost" size="md" disabled={!active} onClick={clear}>
            Clear
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Text filter applied 300 ms after typing stops (keeps the server from recounting on every key). */
function DebouncedInput({ label, value, onChange, placeholder, icon }: { label: string; value: string; onChange: (v: string) => void; placeholder: string; icon?: boolean }) {
  const [text, setText] = useState(value);
  const [seen, setSeen] = useState(value);
  if (value !== seen) {
    // filters cleared from outside
    setSeen(value);
    setText(value);
  }
  useEffect(() => {
    if (text.trim() === value) return;
    const t = setTimeout(() => onChange(text.trim()), 300);
    return () => clearTimeout(t);
  }, [text, value, onChange]);
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-xs font-semibold text-foreground/75">{label}</span>
      <span className="relative">
        {icon && <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden />}
        <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={100} placeholder={placeholder} className={icon ? "pl-8" : undefined} />
      </span>
    </label>
  );
}

function Pager({ page, pageSize, total, loading, onPage }: { page: number; pageSize: number; total: number; loading: boolean; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total ? (page - 1) * pageSize + 1 : 0;
  const to = Math.min(page * pageSize, total);
  return (
    <nav aria-label="GP pages" className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm">
      <span className="text-muted-foreground">
        Showing {formatCount(from)}–{formatCount(to)} of {formatCount(total)} GPs
      </span>
      <span className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => onPage(page - 1)} disabled={page <= 1 || loading}>
          <ChevronLeft /> Previous
        </Button>
        <span className="tabular text-muted-foreground">
          Page {page} of {pages}
        </span>
        <Button variant="outline" size="sm" onClick={() => onPage(page + 1)} disabled={page >= pages || loading}>
          Next <ChevronRight />
        </Button>
      </span>
    </nav>
  );
}

/** One GP: overall record, every ticket it was in, date-wise history (status, remark, proof of each submission). */
function GpDetailDialog({ gpCode, onClose }: { gpCode: string | null; onClose: () => void }) {
  const q = useApiQuery(gpCode ? `gp-detail:${gpCode}` : null, () => ticketApi.getGpMonitorDetail(gpCode!));
  const d = q.data;
  return (
    <Dialog open={!!gpCode} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="top-[5vh] max-h-[90vh] max-w-4xl overflow-y-auto">
        <div className="space-y-4 p-6">
          <div className="flex flex-wrap items-start justify-between gap-2 pr-8">
            <div>
              <DialogTitle className="text-lg font-bold">
                GP {gpCode}
                {d && ` · ${d.gpName}`}
              </DialogTitle>
              <DialogDescription className="mt-0.5 text-[0.8125rem] text-muted-foreground">GP-wise task details, remarks, proof documents and the date-wise submission history</DialogDescription>
            </div>
            {d && <GpCategoryBadge code={d.gpCategory} className="text-[0.75rem]" />}
          </div>
          {q.error ? (
            <ErrorState error={q.error} onRetry={q.reload} className="py-6" />
          ) : !d ? (
            <TableSkeleton rows={6} />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-x-5 gap-y-3 rounded-lg border border-border px-4 py-3 text-[0.8125rem] sm:grid-cols-4">
                <Info label="Circle">{d.circle}</Info>
                <Info label="Area Manager">{d.areaManager}</Info>
                <Info label="Field Engineer">{d.fieldEngineer ?? "Not mapped"}</Info>
                <Info label="Block Name">{d.block ?? "—"}</Info>
                <Info label="District">{d.district ?? "—"}</Info>
                <Info label="Ticket ID">
                  {d.ticket} <TicketStatusBadge status={d.ticketStatus} />
                </Info>
                <Info label="Assigned Week">
                  {wk(d.week)} ({ticketDay(d.weekStart)} – {ticketDay(d.weekEnd)})
                </Info>
                <Info label="Weekly Target">{d.target}</Info>
                <Info label="Total Achievement / Gap">
                  <span className="text-good-text">{d.achieved}</span> / <span className={d.gap > 0 ? "text-critical-text" : "text-good-text"}>{d.gap}</span>
                </Info>
                <Info label="Selected Status">
                  <GpCategoryBadge code={d.gpCategory} />
                  {d.categoryAt && (
                    <span className="block text-[0.71875rem] font-normal text-muted-foreground">
                      {ticketTime(d.categoryAt)}
                      {d.categoryTicket && ` · ${d.categoryTicket}`}
                    </span>
                  )}
                </Info>
                <Info label="Planned Date">{d.plannedDate ? ticketDay(d.plannedDate) : "—"}</Info>
                <Info label="Last Updated">{d.lastUpdated ? ticketTime(d.lastUpdated) : "No submission yet"}</Info>
                <div className="col-span-2">
                  <Info label="Latest remark">{d.remarks ?? <span className="font-normal text-muted-foreground">No Remarks Submitted</span>}</Info>
                </div>
                <div className="col-span-2 sm:col-span-4">
                  <dt className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">Uploaded Documents</dt>
                  <dd className="mt-1">
                    <ProofList files={d.files} emptyText="Not Attached" />
                  </dd>
                </div>
              </dl>

              {d.ticketRows.length > 1 && (
                <div>
                  <h4 className="mb-1.5 text-[0.84375rem] font-bold text-subheading">In {d.ticketRows.length} tickets (counted once)</h4>
                  <div className="flex flex-wrap gap-2">
                    {d.ticketRows.map((r) => (
                      <span key={r.ticket} className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-[0.75rem]">
                        <b>{r.ticket}</b> · {wk(r.week)} · {r.kind === "WEEK" ? "this week" : "pending from earlier"} · {r.achieved}/{r.target} <GpCategoryBadge code={r.gpCategory} />
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <h4 className="mb-1.5 text-[0.84375rem] font-bold text-subheading">Daily Submission History</h4>
                {d.history.length === 0 ? (
                  <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-[0.8125rem] text-muted-foreground">Nothing has been submitted for this GP yet.</p>
                ) : (
                  <div className="max-h-[20rem] overflow-auto rounded-lg border border-border">
                    <table className="w-full min-w-[45rem] text-[0.78125rem]">
                      <thead className="sticky top-0 bg-muted">
                        <tr className="text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                          {["Date", "Ticket", "Status", "Remarks", "Document"].map((h) => (
                            <th key={h} className="px-3 py-1.5">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="tabular">
                        {d.history.map((h, i) => (
                          <tr key={i} className="border-t border-border/60 align-top">
                            <td className="whitespace-nowrap px-3 py-1.5">
                              {h.at ? (h.at.includes("T") ? ticketTime(h.at) : ticketDay(h.at)) : "—"}
                              <span className="block text-[0.6875rem] text-muted-foreground">{h.by}</span>
                            </td>
                            <td className="whitespace-nowrap px-3 py-1.5">
                              {h.ticket}
                              <span className="block text-[0.6875rem] text-muted-foreground">{wk(h.week)}</span>
                            </td>
                            <td className="px-3 py-1.5">{h.gpCategory ? <GpCategoryBadge code={h.gpCategory} /> : <GpStatusBadge status={h.status} />}</td>
                            <td className="max-w-[15rem] px-3 py-1.5">{h.remark ?? <span className="text-muted-foreground">No Remarks</span>}</td>
                            <td className="min-w-[10rem] px-3 py-1.5">
                              <ProofList files={h.files} compact emptyText={h.source === "master" ? "—" : "Not Attached"} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Info({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-semibold">{children}</dd>
    </div>
  );
}

export type { GpMonitorRow };
