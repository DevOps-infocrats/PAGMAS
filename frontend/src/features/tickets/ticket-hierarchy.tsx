"use client";

import { ChevronDown, ChevronRight, GitBranch, Layers, Loader2, Lock, RadioTower, Search, UserRound, X } from "lucide-react";
import { useState } from "react";
import { ErrorState } from "@/components/feedback/states";
import { MiniKpi } from "@/components/kpi/mini-kpi";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { ticketApi, type TicketDetail, type TicketHierarchyQuery, type TicketLevel, type TicketUnitBrief, type TicketUnitRow } from "@/lib/api";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";
import { ticketTime } from "./ticket-parts";

/**
 * Ticket hierarchy: AM ticket (TKT-000123) → FE tickets (TKT-000123-FE-01) → FRT tickets, one per GP
 * (TKT-000123-FE-01-FRT-001). Every ticket has its own status and history – none is closed by another one.
 * Backend: app/tickets/units.py.
 */

const TONE: Record<string, string> = {
  OPEN: "bg-muted text-muted-foreground",
  IN_PROGRESS: "bg-[color-mix(in_oklab,var(--series-1)_16%,transparent)] text-[var(--series-1)]",
  PENDING_REVIEW: "bg-warning-soft text-warning-text",
  CHANGES_REQUESTED: "bg-warning-soft text-warning-text",
  CLOSED: "bg-good-soft text-good-text",
};
const LEVEL_TONE: Record<TicketLevel, string> = { AM: "bg-primary text-primary-foreground", FE: "bg-[var(--series-2)] text-white", FRT: "bg-[var(--series-4)] text-white" };
const LEVEL_LABEL: Record<TicketLevel, string> = { AM: "AM tickets", FE: "FE tickets", FRT: "FRT tickets (one per GP)" };
const STATUS_TEXT: Record<string, string> = { OPEN: "Open", IN_PROGRESS: "In Progress", PENDING_REVIEW: "Pending", CHANGES_REQUESTED: "Changes requested", CLOSED: "Closed" };

export function UnitStatusBadge({ status, label }: { status: string; label?: string }) {
  return <span className={cn("inline-block whitespace-nowrap rounded px-1.5 py-0.5 text-[0.6875rem] font-semibold", TONE[status] ?? TONE.OPEN)}>{label ?? STATUS_TEXT[status] ?? status}</span>;
}

export function LevelBadge({ level }: { level: TicketLevel }) {
  return <span className={cn("inline-block w-9 rounded px-1 py-0.5 text-center text-[0.625rem] font-bold", LEVEL_TONE[level])}>{level}</span>;
}

const errText = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Something went wrong");

// ---------------------------------------------------------------- Admin: every level in one list

const EMPTY: TicketHierarchyQuery = { page: 1, pageSize: 50 };

export function HierarchyAdminView({ onOpenTicket }: { onOpenTicket: (ticketId: number) => void }) {
  const [q, setQ] = useState<TicketHierarchyQuery>(EMPTY);
  const [draft, setDraft] = useState<TicketHierarchyQuery>(EMPTY);
  const [unit, setUnit] = useState<{ ticketId: number; unitId: number } | null>(null);
  const [tick, setTick] = useState(0);
  const res = useApiQuery(`ticket-hierarchy:${tick}:${JSON.stringify(q)}`, () => ticketApi.getHierarchy(q));
  const data = res.data ?? res.staleData;
  const apply = (next: TicketHierarchyQuery) => {
    const v = { ...next, page: 1, pageSize: 50 };
    setDraft(v);
    setQ(v);
  };
  const drill = (r: TicketUnitRow) => apply({ ...EMPTY, search: r.code }); // the ticket and everything under it
  const filtered = Object.entries(q).some(([k, v]) => !["page", "pageSize"].includes(k) && v);
  const field = (k: keyof TicketHierarchyQuery, ph: string, w = "w-36") => (
    <Input className={cn("h-9", w)} placeholder={ph} value={(draft[k] as string) ?? ""} onChange={(e) => setDraft({ ...draft, [k]: e.target.value || undefined })} />
  );
  const select = (k: "level" | "status", opts: [string, string][], ph: string) => (
    <select
      aria-label={ph}
      className="h-9 rounded-md border border-input bg-background px-2 text-sm"
      value={(draft[k] as string) ?? ""}
      onChange={(e) => apply({ ...draft, [k]: e.target.value || undefined })}
    >
      <option value="">{ph}</option>
      {opts.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </select>
  );
  const levels: TicketLevel[] = ["AM", "FE", "FRT"];
  const icon = { AM: UserRound, FE: GitBranch, FRT: RadioTower };
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {levels.map((lv) => {
          const c = data?.counts?.[lv];
          return (
            <MiniKpi
              key={lv}
              loading={!data}
              icon={icon[lv]}
              tone={lv === "AM" ? "var(--primary)" : lv === "FE" ? "var(--series-2)" : "var(--series-4)"}
              label={LEVEL_LABEL[lv]}
              info={`Each ${lv} ticket counted once (a parent and its children are never added together)${filtered ? " – of the tickets matching the filters" : ""}. Click to list only ${lv} tickets.`}
              value={formatCount(c?.total ?? 0)}
              unit="tickets"
              caption={c ? `${formatCount(c.OPEN ?? 0)} open · ${formatCount(c.IN_PROGRESS ?? 0)} in progress · ${formatCount((c.PENDING_REVIEW ?? 0) + (c.CHANGES_REQUESTED ?? 0))} pending · ${formatCount(c.CLOSED ?? 0)} closed` : undefined}
              onClick={() => apply({ ...draft, level: q.level === lv ? undefined : lv })}
              active={q.level === lv}
            />
          );
        })}
      </div>

      <Card className="overflow-hidden p-0">
        <form
          className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            apply(draft);
          }}
        >
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
            <Input className="h-9 w-64 pl-8" placeholder="Any ticket ID (AM / FE / FRT)" value={draft.search ?? ""} onChange={(e) => setDraft({ ...draft, search: e.target.value || undefined })} />
          </div>
          {select("level", levels.map((l) => [l, `${l} tickets`]), "All levels")}
          {select("status", [["OPEN", "Open"], ["IN_PROGRESS", "In Progress"], ["PENDING_REVIEW", "Pending"], ["CLOSED", "Closed"]], "All statuses")}
          {field("am", "Area Manager")}
          {field("fe", "FE")}
          {field("frt", "FRT team", "w-28")}
          {field("gp", "GP code / name")}
          <Input type="date" aria-label="Generated from" className="h-9 w-36" value={draft.dateFrom ?? ""} onChange={(e) => setDraft({ ...draft, dateFrom: e.target.value || undefined })} />
          <Input type="date" aria-label="Generated to" className="h-9 w-36" value={draft.dateTo ?? ""} onChange={(e) => setDraft({ ...draft, dateTo: e.target.value || undefined })} />
          <Button type="submit" size="sm" variant="primary">
            Apply
          </Button>
          {filtered && (
            <Button type="button" size="sm" variant="outline" onClick={() => apply(EMPTY)}>
              <X /> Clear
            </Button>
          )}
        </form>
        {res.error ? (
          <div className="p-5">
            <ErrorState error={res.error} onRetry={res.reload} />
          </div>
        ) : !data ? (
          <p className="flex items-center gap-2 p-5 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Loading the tickets…
          </p>
        ) : !data.items.length ? (
          <p className="p-6 text-center text-sm text-muted-foreground">No ticket matches.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[64rem] text-[0.8125rem]">
              <thead className="bg-muted/60 text-left text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                <tr>
                  {["Level", "Ticket ID", "Status", "Area Manager", "FE", "FRT", "GP", "Under it", "Updated", ""].map((h) => (
                    <th key={h} className="px-3 py-2 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={`${r.level}:${r.id}`} className={cn("border-t border-border align-top hover:bg-accent/30", r.level === "AM" && "bg-muted/20")}>
                    <td className="px-3 py-2">
                      <LevelBadge level={r.level} />
                    </td>
                    <td className={cn("whitespace-nowrap px-3 py-2 font-mono text-[0.75rem]", r.level === "FE" && "pl-6", r.level === "FRT" && "pl-10")}>
                      <button
                        type="button"
                        className="font-semibold text-primary hover:underline"
                        title={r.level === "AM" ? "Open the AM ticket" : "Open this ticket and its history"}
                        onClick={() => (r.level === "AM" ? onOpenTicket(r.ticketId) : setUnit({ ticketId: r.ticketId, unitId: r.id }))}
                      >
                        {r.code}
                      </button>
                      {r.level !== "AM" && <span className="block text-[0.6875rem] text-muted-foreground">under {r.parentCode}</span>}
                    </td>
                    <td className="px-3 py-2">
                      <UnitStatusBadge status={r.status} label={r.statusLabel} />
                    </td>
                    <td className="px-3 py-2">{r.am ?? "—"}</td>
                    <td className="px-3 py-2">{r.fe ?? "—"}</td>
                    <td className="px-3 py-2">{r.frt ?? "—"}</td>
                    <td className="px-3 py-2">{r.gpCode ? `${r.gpCode} · ${r.gpName ?? ""}` : "—"}</td>
                    <td className="whitespace-nowrap px-3 py-2">
                      {r.level === "FRT" || !r.children || r.children.fe + r.children.frt === 0 ? (
                        <span className="text-muted-foreground">—</span>
                      ) : (
                        <button type="button" className="text-primary hover:underline" onClick={() => drill(r)} title="Show this ticket with everything under it">
                          {r.level === "AM" ? `${r.children.fe} FE · ${r.children.frt} FRT` : `${r.children.frt} FRT`} · {r.children.open} not closed
                          <ChevronRight className="ml-0.5 inline size-3.5" aria-hidden />
                        </button>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{ticketTime(r.updatedAt)}</td>
                    <td className="px-3 py-2">
                      {r.level !== "AM" && (
                        <Button size="sm" variant="outline" onClick={() => setUnit({ ticketId: r.ticketId, unitId: r.id })}>
                          History
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > data.pageSize && (
          <div className="flex items-center justify-between border-t border-border px-4 py-2 text-[0.8125rem] text-muted-foreground">
            <span>
              {formatCount((data.page - 1) * data.pageSize + 1)}–{formatCount(Math.min(data.total, data.page * data.pageSize))} of {formatCount(data.total)}
            </span>
            <span className="flex gap-2">
              <Button size="sm" variant="outline" disabled={data.page <= 1} onClick={() => setQ({ ...q, page: (q.page ?? 1) - 1 })}>
                Previous
              </Button>
              <Button size="sm" variant="outline" disabled={data.page * data.pageSize >= data.total} onClick={() => setQ({ ...q, page: (q.page ?? 1) + 1 })}>
                Next
              </Button>
            </span>
          </div>
        )}
      </Card>
      <UnitDialog unit={unit} onClose={() => setUnit(null)} onChanged={() => setTick((x) => x + 1)} />
    </div>
  );
}

// ---------------------------------------------------------------- one FE / FRT ticket

export function UnitDialog({ unit, onClose, onChanged }: { unit: { ticketId: number; unitId: number } | null; onClose: () => void; onChanged?: () => void }) {
  const [tick, setTick] = useState(0);
  const q = useApiQuery(unit ? `ticket-unit:${unit.ticketId}:${unit.unitId}:${tick}` : null, () => ticketApi.getUnit(unit!.ticketId, unit!.unitId));
  const d = q.data;
  const [remark, setRemark] = useState("");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const close = async () => {
    if (!unit) return;
    setBusy(true);
    setErr(null);
    try {
      await ticketApi.closeUnit(unit.ticketId, unit.unitId, { remark: remark.trim() || undefined, force });
      setRemark("");
      setForce(false);
      setTick((x) => x + 1);
      onChanged?.();
    } catch (e) {
      setErr(errText(e));
      if (e instanceof ApiError && e.status === 409 && !force) setForce(true); // GPs not approved: offer "close anyway"
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={!!unit} onOpenChange={(o) => !o && (onClose(), setErr(null), setForce(false), setRemark(""))}>
      <DialogContent className="top-[5vh] max-h-[90dvh] max-w-3xl overflow-y-auto">
        <div className="space-y-4 p-5">
          {q.error ? (
            <ErrorState error={q.error} onRetry={q.reload} />
          ) : !d ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading…
            </p>
          ) : (
            <>
              <div>
                <DialogTitle className="flex flex-wrap items-center gap-2 text-lg font-bold">
                  <LevelBadge level={d.level} /> <span className="font-mono">{d.code}</span> <UnitStatusBadge status={d.status} label={d.statusLabel} />
                </DialogTitle>
                <DialogDescription className="mt-1 text-[0.8125rem] text-muted-foreground">
                  {d.level === "FE" ? `FE ticket of ${d.fe}` : `FRT ticket of GP ${d.gpCode} – ${d.gpName ?? ""} (FRT ${d.frt})`} under {d.parentCode} · AM ticket {d.amCode}. Its status is its own – it never closes, and is
                  never closed by, its AM, FE or FRT tickets.
                </DialogDescription>
              </div>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[0.8125rem] sm:grid-cols-3">
                {(
                  [
                    ["Area Manager", d.am],
                    ["FE", d.fe],
                    ...(d.level === "FRT" ? [["FRT team", d.frt], ["GP", d.gpCode ? `${d.gpCode} · ${d.gpName ?? ""}` : null], ["Block", d.block], ["GP now", d.gpStage]] : []),
                    ["Circle", d.circle],
                    ["Week", d.week],
                    ["Created", ticketTime(d.createdAt)],
                    ["Started", d.startedAt ? ticketTime(d.startedAt) : "—"],
                    ["Closed", d.closedAt ? `${ticketTime(d.closedAt)} · ${d.closedBy ?? ""}` : "—"],
                  ] as [string, string | null | undefined][]
                ).map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-[0.6875rem] uppercase tracking-wide text-muted-foreground">{k}</dt>
                    <dd className="font-medium">{v || "—"}</dd>
                  </div>
                ))}
              </dl>
              {d.closeRemark && <p className="rounded-md bg-muted/50 px-3 py-2 text-[0.8125rem]">Closing remark: {d.closeRemark}</p>}
              {d.frtTickets && d.frtTickets.length > 0 && (
                <section>
                  <h3 className="mb-1 text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">FRT tickets under it ({d.frtTickets.length})</h3>
                  <ul className="divide-y divide-border rounded-md border border-border">
                    {d.frtTickets.map((c) => (
                      <li key={c.id} className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-[0.8125rem]">
                        <span className="font-mono text-[0.75rem]">{c.code}</span> <UnitStatusBadge status={c.status} label={c.statusLabel} />
                        <span className="text-muted-foreground">
                          GP {c.gpCode} · {c.gpName} · FRT {c.frt}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              <section>
                <h3 className="mb-1 text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">History</h3>
                <ol className="relative space-y-2 border-l-2 border-border pl-4 text-[0.8125rem]">
                  {d.history.map((h, i) => (
                    <li key={i}>
                      <span className="text-[0.75rem] text-muted-foreground">{ticketTime(h.at)}</span> · <b>{h.action.replaceAll("_", " ").toLowerCase()}</b>
                      {h.to && h.from !== h.to && (
                        <>
                          {" "}
                          → <UnitStatusBadge status={h.to} />
                        </>
                      )}{" "}
                      <span className="text-muted-foreground">by {h.by}</span>
                      {h.note && <span className="block text-muted-foreground">{h.note}</span>}
                    </li>
                  ))}
                </ol>
              </section>
              {d.canClose && (
                <section className="space-y-2 rounded-lg border border-border p-3">
                  <h3 className="flex items-center gap-1.5 text-sm font-semibold">
                    <Lock className="size-4 text-primary" aria-hidden /> Close this FE ticket (Area Manager)
                  </h3>
                  <p className="text-[0.75rem] text-muted-foreground">Possible once you have approved this FE&apos;s GPs – otherwise only with a written reason. The AM ticket and the FRT tickets stay as they are.</p>
                  <textarea
                    className="min-h-16 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    placeholder={force ? "Reason for closing without approving every GP (at least 10 characters)" : "Remark (optional)"}
                    value={remark}
                    maxLength={1000}
                    onChange={(e) => setRemark(e.target.value)}
                  />
                  {force && (
                    <label className="flex items-center gap-2 text-[0.8125rem]">
                      <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> Close anyway (GPs not approved yet)
                    </label>
                  )}
                  {err && (
                    <p role="alert" className="rounded-md bg-critical-soft px-3 py-2 text-[0.8125rem] text-critical-text">
                      {err}
                    </p>
                  )}
                  <Button variant="primary" size="sm" onClick={close} disabled={busy}>
                    {busy ? <Loader2 className="animate-spin" /> : <Lock />} Close FE ticket
                  </Button>
                </section>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- the user's own ticket ID (lists, header, GP rows)

/** The FRT ticket ID of one GP row (under the GP code in the ticket's GP tables). */
export function GpTicketId({ t, gpId }: { t: { gpUnits?: Record<string, TicketUnitBrief> }; gpId: number }) {
  const u = t.gpUnits?.[String(gpId)];
  if (!u) return null;
  return (
    <span className="mt-0.5 block whitespace-nowrap font-mono text-[0.625rem] text-muted-foreground" title={`FRT ticket of this GP – ${u.statusLabel}`}>
      {u.code} <UnitStatusBadge status={u.status} label={u.status === "PENDING_REVIEW" ? "Pending FE" : undefined} />
    </span>
  );
}

// ---------------------------------------------------------------- one AM ticket: its tree (ticket detail)

export function TicketHierarchyPanel({ t }: { t: TicketDetail }) {
  const [tick, setTick] = useState(0);
  const q = useApiQuery(`ticket-tree:${t.id}:${t.updatedAt}:${tick}`, () => ticketApi.getTicketHierarchy(t.id));
  const d = q.data ?? q.staleData;
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [unit, setUnit] = useState<{ ticketId: number; unitId: number } | null>(null);
  if (q.error) return null; // never in the way of the ticket itself
  if (!d || (!d.fe.length && !d.frtDirect.length)) return null;
  const row = (u: TicketUnitRow, depth: number, toggle?: () => void, isOpen?: boolean, extra?: string) => (
    <li key={`${u.level}:${u.id}`} className={cn("flex flex-wrap items-center gap-2 px-3 py-1.5 text-[0.8125rem]", depth === 1 && "pl-8")}>
      {toggle ? (
        <button type="button" onClick={toggle} aria-expanded={isOpen} className="text-muted-foreground" title={isOpen ? "Hide its FRT tickets" : "Show its FRT tickets"}>
          {isOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        </button>
      ) : (
        <span className="w-4" />
      )}
      <LevelBadge level={u.level} />
      <button type="button" className="font-mono text-[0.75rem] font-semibold text-primary hover:underline" onClick={() => setUnit({ ticketId: t.id, unitId: u.id })}>
        {u.code}
      </button>
      <UnitStatusBadge status={u.status} label={u.statusLabel} />
      <span className="text-muted-foreground">{u.level === "FE" ? u.fe : `GP ${u.gpCode} · ${u.gpName ?? ""} · FRT ${u.frt}`}</span>
      {extra && <span className="ml-auto text-[0.75rem] text-muted-foreground">{extra}</span>}
    </li>
  );
  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5">
        <Layers className="size-4 text-primary" aria-hidden />
        <h3 className="text-[0.9375rem] font-bold text-subheading">Ticket hierarchy</h3>
        <span className="text-[0.75rem] text-muted-foreground">
          {d.ticket.code} → {d.fe.length} FE ticket{d.fe.length === 1 ? "" : "s"} → {d.fe.reduce((n, f) => n + f.frt.length, 0) + d.frtDirect.length} FRT ticket(s). Each has its own status.
          {d.canCloseFe ? " As the Area Manager you close the FE tickets." : ""}
        </span>
      </div>
      <ul className="divide-y divide-border">
        {d.fe.map((f) => (
          <li key={f.id}>
            <ul>
              {row(f, 0, f.frt.length ? () => setOpen({ ...open, [f.id]: !open[f.id] }) : undefined, !!open[f.id], f.frt.length ? `${f.counts.CLOSED ?? 0}/${f.counts.total} FRT closed` : "no FRT ticket")}
              {open[f.id] && f.frt.map((c) => row(c, 1))}
            </ul>
          </li>
        ))}
        {d.frtDirect.map((c) => row(c, 0, undefined, undefined, "directly under the AM ticket"))}
      </ul>
      <UnitDialog unit={unit} onClose={() => setUnit(null)} onChanged={() => setTick((x) => x + 1)} />
    </Card>
  );
}
