"use client";

import { ChevronDown, CircleCheck, CirclePause, Layers, Loader2, Plus, RotateCcw, ShieldCheck, Trash2, UserRound, Wrench } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { MiniKpi } from "@/components/kpi/mini-kpi";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { IS_LIVE, ticketApi, type GpReviewState, type TicketDetail, type TicketKpis, type TicketListFilters, type TicketSummary, type TicketWorkTotals } from "@/lib/api";
import { formatCount } from "@/lib/utils/format";
import {
  ActivityLog,
  BackToList,
  CODE_COL,
  CREATED_COL,
  ConfirmDialog,
  EMPTY_FILTERS,
  NoticeBar,
  PRIORITY_COL,
  STATUS_COL,
  SUBJECT_COL,
  SubmissionHistory,
  TicketFilterBar,
  TicketInfo,
  TicketTable,
  listQuery,
  ticketIdFrom,
  ticketTime,
  type ListFilters,
  type Notice,
  type TicketColumn,
} from "./ticket-parts";
import { GenerateTicketDialog } from "./generate-ticket-dialog";
import { CategoryKpiCards, GpMonitorView, categoryFrom } from "./gp-monitor";
import { CATEGORY } from "./gp-category";
import { RecipientsCard } from "./ticket-recipients";
import { TaskPanel } from "./ticket-task";
import { HierarchyAdminView, LevelBadge, TicketHierarchyPanel, UnitDialog, UnitStatusBadge } from "./ticket-hierarchy";

/** GP review states that count as reviewed by the Area Manager (backend: review.AM_REVIEWED – not one the SME sent back). */
const REVIEWED: GpReviewState[] = ["AM_APPROVED", "SME_FORWARDED", "COH_RETURNED", "LETTER_SUBMITTED", "AMC_CONVERTED", "ND_APPROVED"];

const COLUMNS: TicketColumn[] = [
  CODE_COL,
  { key: "user", header: "Assigned User", render: (t) => <span className="whitespace-nowrap font-medium">{t.assignee.name}</span> },
  { key: "email", header: "Email ID", render: (t) => <span className="text-muted-foreground">{t.assignee.email}</span> },
  {
    key: "circle",
    header: "Circle / Task",
    render: (t) =>
      t.circle || t.areaManager ? (
        <span className="whitespace-nowrap text-[0.78125rem]">
          {t.circle ?? "—"}
          {t.areaManager && (
            <span className="block text-muted-foreground">
              {t.areaManager} · {t.week?.replace("W-", "Wk ")}
            </span>
          )}
          {!!t.recipientCount && t.recipientCount > 1 && <span className="block text-muted-foreground">{t.recipientCount} recipients</span>}
        </span>
      ) : (
        <span className="text-muted-foreground">—</span>
      ),
  },
  {
    key: "progress",
    header: "Progress",
    render: (t) => {
      const w = t.work;
      if (!w) return <span className="text-muted-foreground">—</span>;
      const pct = w.gps ? Math.round((w.filled * 100) / w.gps) : 0;
      return (
        <span className="block min-w-[10rem] whitespace-nowrap text-[0.75rem]" title="GPs with a Daily Achievement (or achieved) · who of the ticket's AM, FEs and FRT teams has worked on it">
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-16 overflow-hidden rounded-full bg-muted">
              <span className="block h-full rounded-full bg-[var(--good)]" style={{ width: `${pct}%` }} />
            </span>
            <b>
              {w.filled}/{w.gps}
            </b>{" "}
            GPs filled
          </span>
          <span className="block text-muted-foreground">
            AM {w.amWorked ? "✓" : "✗"} · FE {w.feWorked}/{w.fe} · FRT {w.frtWorked}/{w.frt}
          </span>
        </span>
      );
    },
  },
  SUBJECT_COL,
  PRIORITY_COL,
  CREATED_COL,
  STATUS_COL,
];

export function AdminTicketsView() {
  return (
    <>
      <AdminTickets />
    </>
  );
}

function AdminTickets() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const openId = ticketIdFrom(params.get("ticket"));
  const gpView = categoryFrom(params.get("gps")); // ?gps=a … e: GPs of one category
  const treeView = !openId && !gpView && params.get("view") === "hierarchy"; // ?view=hierarchy: AM → FE → FRT tickets
  const catHref = (c: string) => `${pathname}?gps=${c.toLowerCase()}`;
  const [tick, setTick] = useState(0);
  const [notice, setNotice] = useState<Notice>(null);
  const [creating, setCreating] = useState(false);
  const open = useCallback((id: number | null) => router.push(id ? `${pathname}?ticket=${id}` : pathname, { scroll: true }), [router, pathname]);
  const changed = (n: Notice) => {
    setNotice(n);
    setTick((x) => x + 1);
  };

  if (!IS_LIVE)
    return (
      <Card className="p-6 text-sm text-muted-foreground">
        Ticket Management needs the live backend (NEXT_PUBLIC_API_MODE=live).
      </Card>
    );

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: "Ticket Management" },
          { label: "Admin Tickets", href: pathname },
          ...(openId ? [{ label: "Ticket review" }] : gpView ? [{ label: `${CATEGORY[gpView].label} GPs` }] : treeView ? [{ label: "Ticket hierarchy" }] : []),
        ]}
        title="Admin Tickets"
        description="Assign work to dashboard users, review what they submit, then close the ticket or request changes."
        actions={
          <>
            {(openId || gpView || treeView) && <BackToList onBack={() => open(null)} label="Back to all tickets" />}
            {!openId && !gpView && !treeView && (
              <Button variant="outline" onClick={() => router.push(`${pathname}?view=hierarchy`, { scroll: true })} title="Every AM, FE and FRT ticket – search by any ticket ID, drill down AM → FE → FRT">
                <Layers /> Ticket Hierarchy
              </Button>
            )}
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus /> Generate Ticket
            </Button>
          </>
        }
      />
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
      {openId ? (
        <AdminTicketDetail id={openId} tick={tick} onChanged={changed} />
      ) : gpView ? (
        <GpMonitorView category={gpView} hrefFor={catHref} />
      ) : treeView ? (
        <HierarchyAdminView onOpenTicket={(id) => open(id)} />
      ) : (
        <AdminTicketList tick={tick} onOpen={(id) => open(id)} onChanged={changed} />
      )}
      <GenerateTicketDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={({ codes, emailQueued }) => {
          setCreating(false);
          changed({
            ok: true,
            text: `${codes.length === 1 ? `Ticket ${codes[0]} was` : `${codes.length} tickets (${codes.join(", ")}) were`} created. Recipients with a dashboard account have been notified${emailQueued ? `; e-mail is being sent to ${emailQueued} recipient${emailQueued === 1 ? "" : "s"} – see the ticket for the delivery status` : " (no e-mail sent)"}.`,
          });
        }}
      />
    </div>
  );
}

function AdminKpis({ k, filtered, onWorking }: { k?: TicketKpis; filtered: boolean; onWorking?: () => void }) {
  const L = !k;
  const w = k?.work;
  // Every card counts TICKETS of all three levels – AM tickets (TKT-000123), FE tickets (one per FE) and FRT tickets
  // (one per GP) – and splits them per level in one line. In Progress + Not Started + Closed = Total.
  // (Who works on them – people – is in "Team on these tickets" below.)
  const u = k?.units;
  const am = {
    total: k?.total ?? 0,
    progress: k ? k.byStatus.IN_PROGRESS + k.byStatus.PENDING_REVIEW + k.byStatus.CHANGES_REQUESTED : 0,
    open: k?.byStatus.OPEN ?? 0,
    closed: k?.byStatus.CLOSED ?? 0,
  };
  const lv = (x: "FE" | "FRT") => {
    const c = u?.[x];
    return { total: c?.total ?? 0, progress: (c?.IN_PROGRESS ?? 0) + (c?.PENDING_REVIEW ?? 0), open: c?.OPEN ?? 0, closed: c?.CLOSED ?? 0 };
  };
  const fe = lv("FE");
  const frt = lv("FRT");
  type Key = "total" | "progress" | "open" | "closed";
  const sum = (key: Key) => am[key] + fe[key] + frt[key];
  const split = (key: Key) => (u ? `AM ${formatCount(am[key])} · FE ${formatCount(fe[key])} · FRT ${formatCount(frt[key])}` : `${formatCount(am[key])} AM tickets`);
  const levels = "AM ticket = one per Area Manager · FE ticket = one per Field Engineer under it · FRT ticket = one per GP of an FRT team.";
  const scope = filtered ? " Only the tickets matching the filters above." : "";
  return (
    <div className="space-y-2">
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MiniKpi
        loading={L}
        icon={Layers}
        tone="var(--series-2)"
        label="Total Tickets"
        info={`Every ticket of every level, each counted once. ${levels}${scope}`}
        value={formatCount(sum("total"))}
        unit="tickets"
        caption={split("total")}
      />
      <MiniKpi
        loading={L}
        icon={Wrench}
        tone="var(--series-4)"
        label="Tickets in Progress"
        onClick={w ? onWorking : undefined}
        info={`Tickets on which work has started and that are not closed yet (AM: In Progress, Pending Review, Changes Requested · FE: In Progress · FRT: In Progress or waiting for the FE to verify). ${levels}${scope}${w ? " Click to see which AM tickets are being worked on and by whom." : ""}`}
        value={formatCount(sum("progress"))}
        unit="tickets"
        caption={split("progress")}
      />
      <MiniKpi
        loading={L}
        icon={CirclePause}
        tone="var(--warning)"
        label="Tickets Not Started"
        info={`Tickets still Open – nobody has started working on them yet. ${levels}${scope}`}
        value={formatCount(sum("open"))}
        unit="tickets"
        caption={split("open")}
      />
      <MiniKpi
        loading={L}
        icon={CircleCheck}
        tone="var(--good)"
        label="Closed Tickets"
        info={`Closed tickets – each closed on its own (AM ticket: by the Admin · FE ticket: by its Area Manager · FRT ticket: when the FE verified its GP). Closing one never closes another. ${levels}${scope}`}
        value={formatCount(sum("closed"))}
        unit="tickets"
        caption={split("closed")}
      />
    </div>
    {w && <TeamDropdown w={w} />}
    </div>
  );
}

/** "Team on these tickets": a dropdown under the KPIs – closed by default; open = the people of the tickets per role. */
function TeamDropdown({ w }: { w: TicketWorkTotals }) {
  const [open, setOpen] = useState(false);
  const rows = [
    { role: "AM", label: "Area Managers", n: w.am, worked: w.amWorked, login: w.amLogin ?? w.am },
    { role: "FE", label: "Field Engineers", n: w.fe, worked: w.feWorked, login: w.feLogin ?? w.fe },
    { role: "FRT", label: "FRT teams", n: w.frt, worked: w.frtWorked, login: w.frtLogin ?? w.frt - w.frtNoLogin },
  ];
  const sum = (f: (r: (typeof rows)[number]) => number) => rows.reduce((a, r) => a + f(r), 0);
  const cols = [
    { key: "Assigned", info: "People on the tickets (each counted per ticket)" },
    { key: "Working", info: "Did something on their ticket – a Daily Achievement, a verify / approve / return or a Non-Doable step" },
    { key: "Not started", info: "Nothing done on their ticket yet" },
    { key: "No login", info: "No dashboard login – cannot work on the ticket" },
  ];
  return (
    <Card className="overflow-hidden p-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="team-on-tickets"
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left transition-colors hover:bg-accent/40"
      >
        <ChevronDown className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
        <span className="text-[0.875rem] font-semibold text-subheading">Team on these tickets</span>
        <span className="text-[0.75rem] text-muted-foreground">
          AM / FE / FRT · {formatCount(sum((r) => r.n))} assigned · {formatCount(sum((r) => r.worked))} working
        </span>
        <span className="ml-auto text-[0.75rem] font-medium text-primary">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div id="team-on-tickets" className="overflow-x-auto border-t border-border">
          <table className="w-full min-w-[36rem] text-[0.8125rem]">
            <thead className="bg-muted/60 text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-4 py-2 text-left font-semibold">Role</th>
                {cols.map((c) => (
                  <th key={c.key} className="px-4 py-2 text-right font-semibold" title={c.info}>
                    {c.key}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular">
              {rows.map((r) => (
                <tr key={r.role} className="border-t border-border">
                  <td className="px-4 py-2">
                    <span className="font-semibold">{r.role}</span> <span className="text-[0.75rem] text-muted-foreground">{r.label}</span>
                  </td>
                  <td className="px-4 py-2 text-right font-semibold">{formatCount(r.n)}</td>
                  <td className="px-4 py-2 text-right">{formatCount(r.worked)}</td>
                  <td className="px-4 py-2 text-right">{formatCount(r.n - r.worked)}</td>
                  <td className={`px-4 py-2 text-right ${r.n - r.login > 0 ? "font-semibold text-critical-text" : "text-muted-foreground"}`}>{formatCount(r.n - r.login)}</td>
                </tr>
              ))}
              <tr className="border-t border-border bg-muted/30 font-semibold">
                <td className="px-4 py-2">Total</td>
                <td className="px-4 py-2 text-right">{formatCount(sum((r) => r.n))}</td>
                <td className="px-4 py-2 text-right">{formatCount(sum((r) => r.worked))}</td>
                <td className="px-4 py-2 text-right">{formatCount(sum((r) => r.n - r.worked))}</td>
                <td className="px-4 py-2 text-right">{formatCount(sum((r) => r.n - r.login))}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** "Tickets in Progress": exactly the tickets the card counts – AM, FE and FRT tickets whose work has started and that
 * are not closed (the filters above). AM tickets also show who worked and what was reported; FE / FRT tickets open
 * their own detail and history. */
function WorkingTickets({ open, onClose, f, tick, onOpen }: { open: boolean; onClose: () => void; f: TicketListFilters; tick: number; onOpen: (id: number) => void }) {
  const q = useApiQuery(open ? `ticket-working:${tick}:${JSON.stringify(f)}` : null, () => ticketApi.getWorking(f));
  const [unit, setUnit] = useState<{ ticketId: number; unitId: number } | null>(null);
  const rows = q.data?.tickets ?? [];
  const work = new Map((q.data?.items ?? []).map((x) => [x.id, x]));
  const per = (lv: string) => rows.filter((r) => r.level === lv).length;
  const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
  const chips = (m: Record<string, number>, tone: string) =>
    Object.entries(m).map(([lbl, n]) => (
      <span key={lbl} className={`mr-1 inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[0.6875rem] font-semibold ${tone}`}>
        {n} {lbl}
      </span>
    ));
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="top-[5vh] max-h-[90dvh] max-w-6xl p-0">
        <div className="border-b border-border px-5 py-3">
          <DialogTitle className="text-lg font-bold">
            Tickets in progress <span className="font-normal text-muted-foreground">({rows.length})</span>
          </DialogTitle>
          <DialogDescription className="text-[0.8125rem] text-muted-foreground">
            {q.data ? `AM ${per("AM")} · FE ${per("FE")} · FRT ${per("FRT")} – ` : ""}
            tickets whose work has started and that are not closed – the same tickets as the card. Click an AM ticket to open it, an FE / FRT ticket to see its history.
          </DialogDescription>
        </div>
        <div className="max-h-[72dvh] overflow-auto">
          {q.error ? (
            <div className="p-5">
              <ErrorState error={q.error} onRetry={q.reload} />
            </div>
          ) : !q.data ? (
            <p className="flex items-center gap-2 p-5 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading…
            </p>
          ) : !rows.length ? (
            <p className="p-5 text-center text-sm text-muted-foreground">No ticket is in progress.</p>
          ) : (
            <table className="w-full min-w-[64rem] text-[0.8125rem]">
              <thead className="sticky top-0 z-10 bg-muted text-left text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                <tr>
                  {["Level", "Ticket", "Area Manager", "FE / FRT · GP", "Target GPs", "Status", "Who worked · what was reported", "Waiting for", "Last activity"].map((h) => (
                    <th key={h} className="px-3 py-2 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const w = r.level === "AM" ? work.get(r.ticketId) : undefined;
                  return (
                    <tr
                      key={`${r.level}:${r.id}`}
                      onClick={() => (r.level === "AM" ? onOpen(r.ticketId) : setUnit({ ticketId: r.ticketId, unitId: r.id }))}
                      className="cursor-pointer border-b border-border align-top last:border-0 hover:bg-accent/40"
                    >
                      <td className="px-3 py-2">
                        <LevelBadge level={r.level} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <span className="font-mono text-[0.75rem] font-semibold text-primary">{r.code}</span>
                        <span className="block text-[0.6875rem] text-muted-foreground">
                          {r.level === "AM" ? `${r.circle ?? "—"} · ${r.week?.replace("W-", "Wk ") ?? ""}` : `under ${r.parentCode}`}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">{r.am ?? "—"}</td>
                      <td className="px-3 py-2">
                        {r.level === "FE" ? r.fe : r.level === "FRT" ? `FRT ${r.frt} · GP ${r.gpCode} ${r.gpName ?? ""}` : <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-semibold tabular">{r.targetGps ?? "—"}</td>
                      <td className="px-3 py-2">
                        <UnitStatusBadge status={r.status} label={r.statusLabel} />
                      </td>
                      <td className="px-3 py-2 text-[0.75rem]">
                        {w ? (
                          <>
                            {(w.work.workers ?? []).join(", ") || "—"}
                            <span className="mt-0.5 block">
                              {chips(w.categories, "bg-good-soft text-good-text")}
                              <span className="text-[0.6875rem] text-muted-foreground">
                                {w.work.filled}/{w.work.gps} GPs filled
                              </span>
                            </span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        {w && Object.keys(w.waiting).length ? chips(w.waiting, "bg-warning-soft text-warning-text") : r.level === "FRT" && r.status === "PENDING_REVIEW" ? chips({ "FE to verify": 1 }, "bg-warning-soft text-warning-text") : <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{when(w?.work.lastAt ?? r.updatedAt)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        <UnitDialog unit={unit} onClose={() => setUnit(null)} />
      </DialogContent>
    </Dialog>
  );
}

interface Monitor {
  circle?: string;
  areaManager?: string;
  week?: string;
  gp: string;
  progressDate: string;
}
const NO_MONITOR: Monitor = { gp: "", progressDate: "" };

/** Admin monitoring filters: Circle, Area Manager, Week, GP code / name, daily submission date. */
function MonitorBar({ value, onChange, tick }: { value: Monitor; onChange: (m: Monitor) => void; tick: number }) {
  const opts = useApiQuery(`ticket-filter-options:${tick}`, () => ticketApi.getFilterOptions());
  const [gp, setGp] = useState(value.gp);
  useEffect(() => {
    if (gp.trim() === value.gp) return;
    const t = setTimeout(() => onChange({ ...value, gp: gp.trim() }), 300);
    return () => clearTimeout(t);
  }, [gp, value, onChange]);
  const o = opts.data ?? { circles: [], areaManagers: [], weeks: [] };
  const active = !!(value.circle || value.areaManager || value.week || value.gp || value.progressDate);
  return (
    <div className="grid grid-cols-1 gap-3 border-b border-border bg-muted/30 px-4 py-3 sm:grid-cols-2 xl:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.2fr)_minmax(0,0.9fr)_auto]">
      <SearchableSelect label="Circle" value={value.circle} onChange={(v) => onChange({ ...value, circle: v })} options={o.circles.map((c) => ({ value: c, label: c }))} allowClear clearLabel="All circles" placeholder="All circles" />
      <SearchableSelect label="Area Manager" value={value.areaManager} onChange={(v) => onChange({ ...value, areaManager: v })} options={o.areaManagers.map((c) => ({ value: c, label: c }))} allowClear clearLabel="All Area Managers" placeholder="All Area Managers" />
      <SearchableSelect label="Week" value={value.week} onChange={(v) => onChange({ ...value, week: v })} options={o.weeks.map((w) => ({ value: w, label: w.replace("W-", "Week ") }))} allowClear clearLabel="All weeks" placeholder="All weeks" />
      <label className="flex min-w-0 flex-col gap-1">
        <span className="text-xs font-semibold text-foreground/75">GP Code / GP Name</span>
        <Input value={gp} onChange={(e) => setGp(e.target.value)} maxLength={100} placeholder="e.g. 0123 or GP name" />
      </label>
      <label className="flex min-w-0 flex-col gap-1">
        <span className="text-xs font-semibold text-foreground/75">Submission date</span>
        <Input type="date" value={value.progressDate} onChange={(e) => onChange({ ...value, progressDate: e.target.value })} />
      </label>
      <div className="flex items-end">
        <Button
          variant="ghost"
          size="md"
          disabled={!active}
          onClick={() => {
            setGp("");
            onChange(NO_MONITOR);
          }}
        >
          Clear
        </Button>
      </div>
    </div>
  );
}

export const DELETE_TEXT = "Are you sure you want to delete this ticket? This action may affect its assigned users and associated progress records.";

function AdminTicketList({ tick, onOpen, onChanged }: { tick: number; onOpen: (id: number) => void; onChanged: (n: Notice) => void }) {
  const [filters, setFilters] = useState<ListFilters>(EMPTY_FILTERS);
  const [toDelete, setToDelete] = useState<TicketSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const remove = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      const r = await ticketApi.remove(toDelete.id);
      setToDelete(null);
      onChanged({ ok: true, text: `Ticket ${r.code} was deleted. It no longer appears for the admin, its Area Manager, FEs or other recipients; its progress history is kept.` });
    } catch (e) {
      setToDelete(null);
      onChanged({ ok: false, text: e instanceof Error ? e.message : "The ticket could not be deleted" });
    } finally {
      setDeleting(false);
    }
  };
  const [mon, setMon] = useState<Monitor>(NO_MONITOR);
  const setMonitor = useCallback((m: Monitor) => {
    setMon(m);
    setFilters((f) => ({ ...f, page: 1 }));
  }, []);
  const q = { ...listQuery(filters), circle: mon.circle, areaManager: mon.areaManager, week: mon.week, gp: mon.gp || undefined, progressDate: mon.progressDate || undefined };
  // the KPIs and the GP categories follow the filters (the tickets the list shows)
  const kf = { search: q.search, status: q.status, priority: q.priority, dateFrom: q.dateFrom, dateTo: q.dateTo, circle: q.circle, areaManager: q.areaManager, week: q.week, gp: q.gp, progressDate: q.progressDate };
  const kpis = useApiQuery(`tickets-kpis:all:${tick}:${JSON.stringify(kf)}`, () => ticketApi.getKpis("all", kf));
  const gpKpis = useApiQuery(`ticket-gp-categories:${tick}:${JSON.stringify(kf)}`, () => ticketApi.getGpCategories(kf));
  const list = useApiQuery(`tickets:all:${tick}:${JSON.stringify(q)}`, () => ticketApi.list({ scope: "all", ...q }));
  const pathname = usePathname();
  const [workingOpen, setWorkingOpen] = useState(false);
  const filtered = !!(filters.search || filters.status !== "all" || filters.priority !== "all" || filters.dateFrom || filters.dateTo || mon.circle || mon.areaManager || mon.week || mon.gp || mon.progressDate);
  return (
    <>
      {/* the filters first: the KPIs, the GP categories and the list below follow them */}
      <Card className="overflow-hidden p-0">
        <TicketFilterBar value={filters} onChange={setFilters} searchHint="Ticket ID, user name or subject" withDates />
        <MonitorBar value={mon} onChange={setMonitor} tick={tick} />
      </Card>
      {kpis.error ? (
        <Card>
          <ErrorState error={kpis.error} onRetry={kpis.reload} />
        </Card>
      ) : (
        <AdminKpis k={kpis.data ?? kpis.staleData} filtered={filtered} onWorking={() => setWorkingOpen(true)} />
      )}
      {gpKpis.error ? (
        <Card>
          <ErrorState error={gpKpis.error} onRetry={gpKpis.reload} />
        </Card>
      ) : (
        <CategoryKpiCards k={gpKpis.data ?? gpKpis.staleData} loading={!(gpKpis.data ?? gpKpis.staleData)} hrefFor={(c) => `${pathname}?gps=${c.toLowerCase()}`} />
      )}
      <TicketTable
        title="All tickets"
        page={list.data ?? list.staleData}
        error={list.error}
        loading={list.loading}
        onRetry={list.reload}
        columns={COLUMNS}
        onOpen={(t) => onOpen(t.id)}
        onPage={(page) => setFilters((f) => ({ ...f, page }))}
        filtered={filtered}
        emptyText="Use Generate Ticket to assign the first piece of work to a user."
        rowAction={(t) => (
          <Button
            size="sm"
            variant="ghost"
            className="text-critical-text hover:bg-critical-soft"
            aria-label={`Delete ticket ${t.code}`}
            onClick={(e) => {
              e.stopPropagation();
              setToDelete(t);
            }}
          >
            <Trash2 /> Delete
          </Button>
        )}
        filters={null}
      />
      <WorkingTickets
        open={workingOpen}
        onClose={() => setWorkingOpen(false)}
        f={kf}
        tick={tick}
        onOpen={(id) => {
          setWorkingOpen(false);
          onOpen(id);
        }}
      />
      <ConfirmDialog
        open={toDelete != null}
        onOpenChange={(o) => !o && setToDelete(null)}
        title={toDelete ? `Delete ticket ${toDelete.code}?` : "Delete ticket?"}
        description={DELETE_TEXT}
        confirmLabel="Delete"
        busy={deleting}
        danger
        onConfirm={() => void remove()}
      />
    </>
  );
}

/* ---------------------------------------------------------------- detail & review */

function AdminTicketDetail({ id, tick, onChanged }: { id: number; tick: number; onChanged: (n: Notice) => void }) {
  const [local, setLocal] = useState<TicketDetail | null>(null);
  const q = useApiQuery(`ticket:${id}:${tick}`, () => ticketApi.get(id));
  const [dialog, setDialog] = useState<"close" | "changes" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const t = local && local.id === id && !q.data ? local : (q.data ?? local);
  if (q.error) return <Card><ErrorState error={q.error} onRetry={q.reload} /></Card>;
  if (!t || t.id !== id) return <PageSkeleton />;
  const latest = t.submissions[0];
  // SOP rule 4: GPs the Area Manager has not reviewed / approved yet (an achieved GP needs no review) – the backend
  // refuses the closure unless the admin writes a reason (force)
  const unreviewed = (t.task?.gps ?? []).filter((g) => !(g.review && REVIEWED.includes(g.review)) && g.cumulative < g.target).length;

  const act = async (kind: "close" | "changes", comment: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = kind === "close" ? await ticketApi.close(t.id, comment, unreviewed > 0) : await ticketApi.requestChanges(t.id, comment);
      setLocal(next);
      setDialog(null);
      onChanged({
        ok: true,
        text: kind === "close" ? `${t.code} is closed. ${t.assignee.name} has been notified.` : `Changes requested on ${t.code}. The ticket went back to ${t.assignee.name}.`,
      });
    } catch (e) {
      setDialog(null);
      setError(e instanceof Error ? e.message : "The action failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <TicketInfo t={t} showAssignee />

      {t.can.review && latest ? (
        <Card className="border-[var(--series-7)]/40 p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="text-base font-bold text-subheading">Review submission {latest.version}</h3>
              <p className="text-[0.8125rem] text-muted-foreground">
                Submitted by {latest.submittedBy} · {ticketTime(latest.submittedAt)} · {latest.attachments.length} file{latest.attachments.length === 1 ? "" : "s"}. Read the
                description and the documents below, then decide.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => setDialog("changes")} disabled={busy}>
                <RotateCcw /> Request Changes
              </Button>
              <Button variant="primary" onClick={() => setDialog("close")} disabled={busy}>
                {busy ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Close Ticket
              </Button>
            </div>
          </div>
        </Card>
      ) : t.can.close ? (
        // GP-wise task: the admin closes it once satisfied with the daily progress (it never closes by itself)
        <Card className="p-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 className="text-base font-bold text-subheading">Review the GP-wise progress</h3>
              <p className="text-[0.8125rem] text-muted-foreground">
                {t.task ? `${t.task.totals.achieved} of ${t.task.totals.target} GPs achieved · ${t.task.history.length} daily submission${t.task.history.length === 1 ? "" : "s"}. ` : ""}
                The ticket stays open until you close it.
              </p>
            </div>
            <Button variant="primary" onClick={() => setDialog("close")} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Close Ticket
            </Button>
          </div>
        </Card>
      ) : (
        <Card className="px-5 py-3 text-sm text-muted-foreground">
          {t.status === "CLOSED"
            ? "This ticket is closed – no further action is possible."
            : t.status === "CHANGES_REQUESTED"
              ? `Waiting for ${t.assignee.name} to submit the revised work.`
              : t.status === "PENDING_REVIEW"
                ? "This ticket is assigned to you, so another admin must review it."
                : `Waiting for ${t.assignee.name} to ${t.status === "OPEN" ? "start the work" : "submit the work"}. Review becomes possible after the submission.`}
        </Card>
      )}
      {error && (
        <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-4 py-2.5 text-sm text-critical-text">
          {error}
        </p>
      )}

      {t.task && <TaskPanel t={t} admin onChanged={(next, n) => (setLocal(next), onChanged(n))} />}
      {t.task && <TicketHierarchyPanel t={t} />}

      <div className="grid grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <SubmissionHistory t={t} emptyText="The user has not submitted any work yet." />
        <div className="space-y-5">
          <Card className="p-5">
            <h3 className="flex items-center gap-2 text-base font-bold text-subheading">
              <UserRound className="size-4 text-primary" aria-hidden /> Assigned user
            </h3>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Name</dt>
                <dd className="font-medium">{t.assignee.name}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Email</dt>
                <dd className="truncate font-medium">{t.assignee.email}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Role</dt>
                <dd className="font-medium capitalize">{t.assigneeRole ?? "—"}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted-foreground">Account</dt>
                <dd className={t.assigneeActive ? "font-medium text-good-text" : "font-medium text-warning-text"}>{t.assigneeActive ? "Active" : t.assignee.id ? "Inactive" : "No dashboard account (e-mail only)"}</dd>
              </div>
            </dl>
          </Card>
          <RecipientsCard t={t} onNotice={(n) => onChanged(n)} />
          <ActivityLog t={t} />
        </div>
      </div>

      <ConfirmDialog
        open={dialog === "close"}
        onOpenChange={(o) => setDialog(o ? "close" : null)}
        title={unreviewed > 0 ? `Close ${t.code} without the Area Manager's approval?` : `Close ${t.code}?`}
        description={
          unreviewed > 0
            ? `${unreviewed} GP${unreviewed === 1 ? " is" : "s are"} not yet reviewed and approved by the Area Manager (SOP: no ticket is closed without AM review and approval). Close only after the AM review – or close anyway with a written reason, which is kept in the ticket history.`
            : latest && latest.review === "PENDING"
              ? `You approve submission ${latest.version} of ${t.assignee.name}. The ticket becomes read-only and the user is notified.`
              : `You close the ticket of ${t.assignee.name}. Daily progress stops; all reports and remarks are kept, and every recipient with a dashboard account sees it as Closed and is notified.`
        }
        confirmLabel={unreviewed > 0 ? "Close anyway" : "Close Ticket"}
        busy={busy}
        onConfirm={(c) => act("close", c)}
        comment={
          unreviewed > 0
            ? { label: "Reason for closing without the Area Manager's approval", placeholder: "e.g. Week ended – the remaining GPs are carried to next week's ticket.", required: true, minLength: 10, hint: "Write the reason" }
            : { label: "Comment for the user (optional)", placeholder: "e.g. Thank you – the report is complete.", required: false }
        }
        danger={unreviewed > 0}
      />
      <ConfirmDialog
        open={dialog === "changes"}
        onOpenChange={(o) => setDialog(o ? "changes" : null)}
        title={`Request changes on ${t.code}?`}
        description={`The ticket goes back to ${t.assignee.name}, who sees your comment and can submit revised work.`}
        confirmLabel="Request Changes"
        busy={busy}
        onConfirm={(c) => act("changes", c)}
        comment={{ label: "What needs to be corrected", placeholder: "Explain what is missing or wrong…", required: true }}
      />
    </div>
  );
}
