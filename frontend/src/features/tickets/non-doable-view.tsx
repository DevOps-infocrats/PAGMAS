"use client";

import {
  Ban,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  CircleDashed,
  CircleDot,
  Download,
  Eye,
  FileText,
  Inbox,
  ListX,
  Loader2,
  Search,
  Send,
  ShieldCheck,
  Undo2,
  UserPlus,
  X,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { EmptyState, ErrorState, PageSkeleton, TableSkeleton } from "@/components/feedback/states";
import { MiniKpi } from "@/components/kpi/mini-kpi";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useSession } from "@/hooks/use-session";
import { IS_LIVE, adminApi, ndApi, type NdAction, type NdCaseDetail, type NdCaseRow, type NdFile, type NdRecord, type NdRole, type NdStatus, type ReviewContacts } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";
import { CATEGORY } from "./gp-category";
import { BackToList, NoticeBar, TEXTAREA, fileSize, ticketDay, ticketIdFrom, ticketTime, type Notice } from "./ticket-parts";
import { EMAIL, SendTo, type Typed } from "./ticket-review";

/**
 * Non-Doable GP exception workflow (backend: app/tickets/nondoable.py): FE physical verification (E1) and justification
 * (E2) → Area Manager (E3) → SME (E4) → COH (E5) → Corporate Team – MGG decision (E6). Every permission is checked by
 * the backend; this page only shows what the signed-in user may do.
 */
const MGG = "Corporate Team – MGG";

const STATUS_CLS: Record<NdStatus, string> = {
  PROPOSED: "bg-warning-soft text-warning-text",
  E1_DONE: "bg-warning-soft text-warning-text",
  PENDING_AM: "bg-primary-soft text-primary",
  RETURNED_FE: "bg-critical-soft text-critical-text",
  PENDING_SME: "bg-[color-mix(in_srgb,var(--series-1)_14%,transparent)] text-[var(--series-1)]",
  RETURNED_AM: "bg-critical-soft text-critical-text",
  RETURNED_SME: "bg-critical-soft text-critical-text",
  PENDING_COH: "bg-[color-mix(in_srgb,var(--series-7)_14%,transparent)] text-[var(--series-7)]",
  PENDING_MGG: "bg-[color-mix(in_srgb,var(--series-3)_16%,transparent)] text-[var(--series-3)]",
  APPROVED: "bg-good-soft text-good-text",
  REJECTED: "bg-critical-soft text-critical-text",
  WITHDRAWN: "bg-muted text-muted-foreground",
};

const FILTERS = [
  { value: "all", label: "All cases" },
  { value: "open", label: "Open (in the workflow)" },
  { value: "with_fe", label: "Pending with FE" },
  { value: "pending_am", label: "Pending AM review" },
  { value: "pending_sme", label: "Pending SME review" },
  { value: "pending_coh", label: "Pending COH review" },
  { value: "pending_mgg", label: "Pending MGG approval" },
  { value: "returned", label: "Returned for correction" },
  { value: "approved", label: "Non-Doable – Approved" },
  { value: "rejected", label: "Rejected – Action Required" },
];

const ACTIONS: Record<NdAction, { label: string; title: string; icon: typeof Send; kind: "forward" | "return" | "approve" | "reject" | "withdraw"; to?: "SME" | "COH" }> = {
  AM_FORWARD: { label: "Forward → SME", title: "Forward the case to the SME", icon: Send, kind: "forward", to: "SME" },
  AM_RETURN: { label: "Return to FE", title: "Return the case to the FE for correction", icon: Undo2, kind: "return" },
  SME_RECOMMEND: { label: "Recommend → COH", title: "Recommend Non-Doable to the COH", icon: Send, kind: "forward", to: "COH" },
  SME_RETURN: { label: "Return to AM", title: "Return the case to the Area Manager", icon: Undo2, kind: "return" },
  COH_FORWARD: { label: `Forward → ${MGG}`, title: `Forward the case to the ${MGG}`, icon: Send, kind: "forward" },
  COH_RETURN: { label: "Return for correction", title: "Return the case for correction", icon: Undo2, kind: "return" },
  MGG_APPROVE: { label: "Approve Non-Doable", title: "Approve the GP as Non-Doable", icon: CheckCircle2, kind: "approve" },
  MGG_REJECT: { label: "Reject", title: "Reject the Non-Doable proposal", icon: XCircle, kind: "reject" },
  WITHDRAW: { label: "Withdraw proposal", title: "Withdraw the Non-Doable proposal", icon: X, kind: "withdraw" },
};

export function NdStatusBadge({ status, label }: { status: NdStatus; label: string }) {
  return <span className={cn("inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-[0.71875rem] font-semibold", STATUS_CLS[status])}>{label}</span>;
}

export function NonDoableView() {
  const { session } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const openId = ticketIdFrom(params.get("case"));
  const ticket = ticketIdFrom(params.get("ticket"));
  const [tick, setTick] = useState(0);
  const [notice, setNotice] = useState<Notice>(null);
  const open = useCallback((id: number | null) => router.push(id ? `${pathname}?case=${id}` : pathname, { scroll: true }), [router, pathname]);

  if (!session) return <PageSkeleton />;
  if (!IS_LIVE)
    return (
      <Card className="p-6 text-sm text-muted-foreground">
        Non-Doable Cases need the live backend (NEXT_PUBLIC_API_MODE=live).
      </Card>
    );
  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Ticket Management" }, { label: "Non-Doable Cases", href: pathname }, ...(openId ? [{ label: "Case details" }] : [])]}
        title="Non-Doable Cases"
        description={`GPs proposed Non-Doable: FE physical verification and justification → Area Manager → SME → COH → ${MGG}.`}
        actions={openId ? <BackToList onBack={() => open(null)} label="Back to the cases" /> : undefined}
      />
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
      {openId ? (
        <CaseDetail
          id={openId}
          tick={tick}
          onChanged={(n) => {
            setNotice(n);
            setTick((x) => x + 1);
          }}
        />
      ) : (
        <CaseList tick={tick} ticket={ticket} onOpen={open} onClearTicket={() => router.push(pathname)} />
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- KPIs */

const KPI_SPEC: Record<NdRole, { title: string; cards: [string, string, string][] }> = {
  AM: {
    title: "Area Manager",
    cards: [
      ["proposed", "Total Non-Doable Proposed", "Cases whose justification (E2) reached you"],
      ["pending", "Pending AM Review", "Waiting for your forward to the SME or return to the FE"],
      ["approvedForSme", "Approved for SME", "Cases you forwarded to the SME"],
      ["returnedToFe", "Returned to FE", "Cases you returned to the FE for correction"],
      ["total", "Total Non-Doable Cases", "Every case of your tickets, in any status"],
    ],
  },
  SME: {
    title: "SME",
    cards: [
      ["received", "Total Cases Received", "Cases the Area Manager forwarded to you"],
      ["pending", "Pending SME Review", "Waiting for your recommendation or return"],
      ["recommended", "Recommended Non-Doable", "Cases you recommended to the COH"],
      ["returnedToAm", "Returned to AM", "Cases you returned to the Area Manager"],
      ["forwardedToCoh", "Forwarded to COH", "Cases now with the COH or decided"],
    ],
  },
  COH: {
    title: "COH",
    cards: [
      ["received", "Total Received", "Cases the SME recommended to you"],
      ["pending", "Pending COH Review", "Waiting for your forward or return"],
      ["recommendedToMgg", "Recommended to MGG", `Cases you forwarded to the ${MGG}`],
      ["returned", "Returned for Correction", "Cases you returned to the FE / AM / SME"],
      ["pendingMgg", "Pending MGG Decision", `Waiting for the ${MGG}`],
    ],
  },
  MGG: {
    title: MGG,
    cards: [
      ["received", "Total Received", "Cases the COH forwarded"],
      ["pending", "Pending MGG Approval", "Waiting for your decision"],
      ["approved", "Approved", "Closed as Non-Doable"],
      ["rejected", "Rejected", "Sent back – revisit with the FRT team"],
      ["decided", "Total Decided", "Approved + rejected"],
    ],
  },
  FE: {
    title: "Field Engineer",
    cards: [
      ["total", "My Non-Doable Cases", "Cases of your GPs"],
      ["actionNeeded", "Action Needed", "Verification, justification, correction or revisit pending with you"],
      ["inReview", "In Review", "With the AM / SME / COH / MGG"],
      ["approved", "Approved", "Closed as Non-Doable"],
      ["rejected", "Rejected", "Revisit with the FRT team"],
    ],
  },
};
const TONES = ["var(--series-1)", "var(--warning)", "var(--good)", "var(--critical)", "var(--series-7)"];
const ICONS = [Inbox, CircleDot, CheckCircle2, Undo2, FileText];

function Kpis({ tick }: { tick: number }) {
  const q = useApiQuery(`nd-summary:${tick}`, () => ndApi.getSummary());
  if (q.error)
    return (
      <Card>
        <ErrorState error={q.error} onRetry={q.reload} />
      </Card>
    );
  const s = q.data;
  const blocks = (["AM", "SME", "COH", "MGG", "FE"] as NdRole[]).filter((r) => s?.kpis[r]);
  if (s && !blocks.length) return null;
  return (
    <div className="space-y-4">
      {(s ? blocks : (["AM"] as NdRole[])).map((role) => (
        <section key={role} aria-label={`${KPI_SPEC[role].title} KPIs`} className="space-y-2">
          <h2 className="text-[0.8125rem] font-semibold uppercase tracking-wide text-muted-foreground">{s?.isAdmin ? `${KPI_SPEC[role].title} (all cases)` : KPI_SPEC[role].title}</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {KPI_SPEC[role].cards.map(([key, label, info], i) => (
              <MiniKpi key={key} loading={!s} icon={ICONS[i]} tone={TONES[i]} label={label} info={info} value={formatCount(s?.kpis[role]?.[key])} unit="cases" />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- list */

const PAGE = 15;

function CaseList({ tick, ticket, onOpen, onClearTicket }: { tick: number; ticket: number | null; onOpen: (id: number) => void; onClearTicket: () => void }) {
  const { session } = useSession();
  const [text, setText] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const q = { status: status === "all" ? undefined : status, q: search || undefined, mine, ticket: ticket ?? undefined, page, size: PAGE };
  const list = useApiQuery(`nd-cases:${tick}:${JSON.stringify(q)}`, () => ndApi.listCases(q));
  const data = list.data ?? list.staleData;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1;
  const filtered = !!(search || status !== "all" || mine || ticket);
  return (
    <>
      <Kpis tick={tick} />
      {session?.role === "admin" && <MggMembers />}
      <Card className="overflow-hidden p-0">
        <form
          className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(text.trim());
            setPage(1);
          }}
        >
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={100} placeholder="Case, GP code / name, block, FE, ticket" className="h-9 w-80 pl-8" aria-label="Search cases" />
          </div>
          <Button type="submit" size="sm" variant="outline">
            Search
          </Button>
          <Select
            ariaLabel="Case status"
            value={status}
            onValueChange={(v) => {
              if (!v) return;
              setStatus(v);
              setPage(1);
            }}
            options={FILTERS}
            className="w-60"
          />
          <label className="flex cursor-pointer items-center gap-2 text-[0.8125rem]">
            <input
              type="checkbox"
              className="size-4 accent-[var(--primary)]"
              checked={mine}
              onChange={(e) => {
                setMine(e.target.checked);
                setPage(1);
              }}
            />
            Waiting for my action
          </label>
          {ticket && (
            <button type="button" onClick={onClearTicket} className="inline-flex items-center gap-1 rounded-full bg-primary-soft px-2 py-0.5 text-[0.75rem] font-semibold text-primary">
              Ticket filter <X className="size-3" />
            </button>
          )}
          {(search || status !== "all" || mine) && (
            <button
              type="button"
              onClick={() => {
                setText("");
                setSearch("");
                setStatus("all");
                setMine(false);
                setPage(1);
              }}
              className="text-[0.78125rem] font-medium text-primary hover:underline"
            >
              Clear
            </button>
          )}
        </form>
        {list.error ? (
          <ErrorState error={list.error} onRetry={list.reload} />
        ) : !data ? (
          <div className="p-4">
            <TableSkeleton rows={6} />
          </div>
        ) : data.total === 0 ? (
          <EmptyState
            icon={ListX}
            title={filtered ? "No cases match the filters" : "No Non-Doable cases yet"}
            description={filtered ? "Change or clear the search and filters." : "A case opens when the FE marks a GP Non-Doable – Proposed in the daily progress."}
          />
        ) : (
          <>
            <div className={cn("overflow-x-auto", list.loading && "opacity-60 transition-opacity")}>
              <table className="w-full min-w-[68.75rem] text-[0.8125rem]">
                <caption className="sr-only">Non-Doable cases</caption>
                <thead>
                  <tr className="border-b border-border bg-muted/60 text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                    {["Case", "Ticket", "GP Code", "GP Name", "Block", "FE", "Status", "Pending with", "Updated", ""].map((h) => (
                      <th key={h} scope="col" className="px-3 py-2">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((c) => (
                    <CaseRowView key={c.id} c={c} onOpen={onOpen} />
                  ))}
                </tbody>
              </table>
            </div>
            <nav aria-label="Case pages" className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm">
              <span className="text-muted-foreground">
                Showing {formatCount((data.page - 1) * data.size + 1)}–{formatCount(Math.min(data.page * data.size, data.total))} of {formatCount(data.total)} cases
              </span>
              <span className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={() => setPage(page - 1)} disabled={page <= 1 || list.loading}>
                  <ChevronLeft /> Previous
                </Button>
                <span className="tabular text-muted-foreground">
                  Page {data.page} of {pages}
                </span>
                <Button variant="outline" size="sm" onClick={() => setPage(page + 1)} disabled={page >= pages || list.loading}>
                  Next <ChevronRight />
                </Button>
              </span>
            </nav>
          </>
        )}
      </Card>
    </>
  );
}

function CaseRowView({ c, onOpen }: { c: NdCaseRow; onOpen: (id: number) => void }) {
  return (
    <tr
      tabIndex={0}
      aria-label={`Open case ${c.ref}`}
      onClick={() => onOpen(c.id)}
      onKeyDown={(e) => e.key === "Enter" && onOpen(c.id)}
      className={cn("cursor-pointer border-b border-border/70 last:border-0 hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none", c.mine && "bg-warning-soft/30")}
    >
      <td className="whitespace-nowrap px-3 py-2.5 font-semibold text-primary">
        {c.ref}
        {c.round > 1 && <span className="ml-1 text-[0.6875rem] font-medium text-muted-foreground">round {c.round}</span>}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5">{c.ticketCode}</td>
      <td className="whitespace-nowrap px-3 py-2.5 font-medium">{c.gpCode}</td>
      <td className="px-3 py-2.5">{c.gpName ?? "—"}</td>
      <td className="px-3 py-2.5 text-muted-foreground">{c.block ?? "—"}</td>
      <td className="px-3 py-2.5">{c.fe ?? "—"}</td>
      <td className="px-3 py-2.5">
        <NdStatusBadge status={c.status} label={c.statusLabel} />
        {c.revisitLabel && <span className="mt-0.5 block text-[0.71875rem] text-muted-foreground">{c.revisitLabel}</span>}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5">
        {c.pendingWith ? <span className={cn("font-semibold", c.mine && "text-warning-text")}>{c.mine ? `You (${c.pendingWith})` : c.pendingWith}</span> : <span className="text-muted-foreground">—</span>}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-muted-foreground">{ticketDay(c.updatedAt)}</td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right">
        <Button
          size="sm"
          variant="ghost"
          onClick={(e) => {
            e.stopPropagation();
            onOpen(c.id);
          }}
        >
          <Eye /> View
        </Button>
      </td>
    </tr>
  );
}

/* ---------------------------------------------------------------- Corporate Team – MGG members (admin) */

function MggMembers() {
  const [show, setShow] = useState(false);
  const [tick, setTick] = useState(0);
  const members = useApiQuery(show ? `nd-mgg:${tick}` : null, () => ndApi.listMgg());
  const users = useApiQuery(show ? "nd-mgg-users" : null, () => adminApi.listUsers());
  const [pick, setPick] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ids = new Set((members.data?.members ?? []).map((m) => m.userId));
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setPick("");
      setTick((x) => x + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="p-0">
      <button type="button" onClick={() => setShow(!show)} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left" aria-expanded={show}>
        <span className="flex items-center gap-2 text-[0.875rem] font-semibold">
          <ShieldCheck className="size-4 text-primary" aria-hidden /> {MGG} – authorised accounts
        </span>
        <span className="text-[0.78125rem] text-muted-foreground">{show ? "Hide" : "Manage"}</span>
      </button>
      {show && (
        <div className="space-y-3 border-t border-border px-4 py-3 text-[0.8125rem]">
          <p className="text-muted-foreground">Only these dashboard accounts can approve or reject a Non-Doable case. Choose an existing active account – no account is created here.</p>
          {members.error ? (
            <ErrorState error={members.error} onRetry={members.reload} />
          ) : !members.data ? (
            <TableSkeleton rows={2} />
          ) : members.data.members.length === 0 ? (
            <p className="rounded-md bg-warning-soft px-3 py-2 text-warning-text">No account is authorised yet – the COH cannot forward cases to the {MGG} until one is added.</p>
          ) : (
            <ul className="divide-y divide-border rounded-md border border-border">
              {members.data.members.map((m) => (
                <li key={m.userId} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                  <span>
                    <b className="font-semibold">{m.name}</b> <span className="text-muted-foreground">· {m.email}</span>
                    {!m.active && <span className="ml-1.5 rounded bg-critical-soft px-1.5 py-0.5 text-[0.65625rem] font-semibold text-critical-text">inactive</span>}
                    <span className="ml-2 text-[0.71875rem] text-muted-foreground">
                      added by {m.addedBy} · {ticketDay(m.addedAt)}
                    </span>
                  </span>
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => run(() => ndApi.removeMgg(m.userId))}>
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Select
              ariaLabel="Account to authorise"
              value={pick || undefined}
              onValueChange={(v) => setPick(v ?? "")}
              placeholder={users.data ? "Choose an active account…" : "Loading accounts…"}
              options={(users.data ?? []).filter((u) => u.isActive && !ids.has(u.id)).map((u) => ({ value: String(u.id), label: `${u.name} · ${u.email}` }))}
              className="w-96"
            />
            <Button size="sm" variant="primary" disabled={!pick || busy} onClick={() => run(() => ndApi.addMgg(Number(pick)))}>
              {busy ? <Loader2 className="animate-spin" /> : <UserPlus />} Authorise
            </Button>
          </div>
          {error && (
            <p role="alert" className="text-critical-text">
              {error}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------------- detail */

function CaseDetail({ id, tick, onChanged }: { id: number; tick: number; onChanged: (n: Notice) => void }) {
  const q = useApiQuery(`nd-case:${id}:${tick}`, () => ndApi.getCase(id));
  if (q.error)
    return (
      <Card>
        <ErrorState error={q.error} onRetry={q.reload} />
      </Card>
    );
  const d = q.data;
  if (!d) return <PageSkeleton />;
  const c = d.case;
  return (
    <div className="space-y-5">
      <Card className="space-y-3 p-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 className="text-xl font-bold text-heading">{c.ref}</h2>
          <NdStatusBadge status={c.status} label={c.statusLabel} />
          {c.revisitLabel && <span className="rounded-full bg-warning-soft px-2 py-0.5 text-[0.71875rem] font-semibold text-warning-text">{c.revisitLabel}</span>}
          {c.round > 1 && <span className="text-[0.78125rem] text-muted-foreground">Round {c.round}</span>}
          <span className="ml-auto text-[0.8125rem]">
            Pending with: <b className={cn("font-semibold", c.mine && "text-warning-text")}>{c.pendingWith ? (c.mine ? `You (${c.pendingWith})` : c.pendingWith) : "—"}</b>
          </span>
        </div>
        <dl className="grid gap-x-6 gap-y-2 text-[0.8125rem] sm:grid-cols-2 lg:grid-cols-4">
          <Info k="GP" v={`${d.gp.gpCode} – ${d.gp.gpName}`} />
          <Info k="Block / District" v={`${d.gp.block ?? "—"} / ${d.gp.district ?? "—"}`} />
          <Info k="Circle" v={d.gp.circle} />
          <Info k="Field Engineer" v={c.fe ?? "—"} />
          <Info
            k="Original ticket"
            v={
              <Link href={`/dashboard/tickets/user?ticket=${d.ticket.id}`} className="font-medium text-primary hover:underline">
                {d.ticket.code} · {d.ticket.status === "CLOSED" ? "Closed" : "Open"}
              </Link>
            }
          />
          <Info k="Area Manager" v={d.ticket.areaManager ?? "—"} />
          <Info k="GP category now" v={d.gp.category ? CATEGORY[d.gp.category].label : "Not classified"} />
          <Info k="Proposed by" v={`${c.createdBy} · ${ticketDay(c.createdAt)}`} />
          <Info k="Physical verification" v={c.physicalLabel} />
          <Info k="Evidence" v={c.evidenceLabel} />
          <Info k="Approval" v={c.approvalLabel} />
          {c.decidedBy && <Info k={`${MGG} decision`} v={`${c.decision === "APPROVED" ? "Approved" : "Rejected"} by ${c.decidedBy} · ${ticketDay(c.decidedAt)}`} />}
        </dl>
        {c.decisionRemark && (
          <p className={cn("rounded-md px-3 py-2 text-[0.8125rem]", c.decision === "REJECTED" ? "bg-critical-soft text-critical-text" : "bg-good-soft text-good-text")}>
            <b className="font-semibold">{c.decision === "REJECTED" ? "Rejection reason" : "Decision remark"}:</b> {c.decisionRemark}
          </p>
        )}
        {d.otherRounds.length > 0 && (
          <p className="text-[0.78125rem] text-muted-foreground">
            Other rounds of this GP:{" "}
            {d.otherRounds.map((o, i) => (
              <span key={o.id}>
                {i > 0 && ", "}
                <Link href={`/dashboard/tickets/non-doable?case=${o.id}`} className="font-medium text-primary hover:underline">
                  {o.ref}
                </Link>{" "}
                ({o.statusLabel})
              </span>
            ))}
          </p>
        )}
      </Card>

      <Tracker steps={d.tracker} />
      <ActionPanel d={d} onChanged={onChanged} />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Records records={d.records} />
        <History d={d} />
      </div>
    </div>
  );
}

function Info({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[0.71875rem] font-semibold uppercase tracking-wide text-muted-foreground">{k}</dt>
      <dd className="mt-0.5">{v}</dd>
    </div>
  );
}

const STEP_ICON = { done: CheckCircle2, current: CircleDot, returned: Undo2, pending: CircleDashed, rejected: XCircle, skipped: CircleDashed };
const STEP_CLS = {
  done: "border-good/40 bg-good-soft text-good-text",
  current: "border-primary/50 bg-primary-soft text-primary",
  returned: "border-critical/40 bg-critical-soft text-critical-text",
  pending: "border-border bg-muted/40 text-muted-foreground",
  rejected: "border-critical/40 bg-critical-soft text-critical-text",
  skipped: "border-border bg-muted/40 text-muted-foreground",
};

function Tracker({ steps }: { steps: NdCaseDetail["tracker"] }) {
  return (
    <ol aria-label="Progress" className="grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
      {steps.map((s) => {
        const Icon = STEP_ICON[s.state];
        return (
          <li key={s.stage} className={cn("rounded-lg border px-3 py-2.5", STEP_CLS[s.state])} aria-current={s.state === "current" ? "step" : undefined}>
            <span className="flex items-center gap-1.5 text-[0.75rem] font-bold uppercase tracking-wide">
              <Icon className="size-4" aria-hidden /> {s.stage}
            </span>
            <span className="mt-0.5 block text-[0.78125rem] font-semibold text-foreground">{s.label}</span>
            <span className="block text-[0.71875rem]">
              {s.state === "returned" ? "Returned – correction" : s.state === "current" ? "In progress" : s.state === "rejected" ? "Rejected" : s.by ? `${s.by} · ${ticketDay(s.at)}` : s.state === "done" ? "Done" : "—"}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/* ---------------------------------------------------------------- what the user can do now */

type FormKind = "verify" | "justify" | "revisitCoordination" | "revisitVisit";

function ActionPanel({ d, onChanged }: { d: NdCaseDetail; onChanged: (n: Notice) => void }) {
  const [form, setForm] = useState<FormKind | null>(null);
  const [action, setAction] = useState<NdAction | null>(null);
  const forms: [FormKind, string][] = (
    [
      ["verify", "E1 – Physical verification"],
      ["justify", "E2 – Justification to AM"],
      ["revisitCoordination", "Record FRT coordination"],
      ["revisitVisit", "Record new FRT site visit"],
    ] as [FormKind, string][]
  ).filter(([k]) => d.can[k]);
  const actions = [...d.can.actions, ...(d.can.withdraw ? (["WITHDRAW"] as NdAction[]) : [])];
  const c = d.case;
  if (!forms.length && !actions.length) {
    const why =
      d.ticket.status === "CLOSED"
        ? "The ticket is closed – the case is read-only."
        : c.status === "APPROVED"
          ? "The GP is closed as Non-Doable."
          : c.status === "REJECTED" && c.revisit === "FRT_UPDATED"
            ? "The FRT visit is recorded – the FE reviews the GP in the daily progress of the ticket (choose its category again)."
            : c.pendingWith
              ? `Waiting for ${c.pendingWith}.`
              : null;
    return why ? <p className="rounded-lg border border-border bg-muted/40 px-4 py-2.5 text-[0.8125rem] text-muted-foreground">{why}</p> : null;
  }
  return (
    <Card className="flex flex-wrap items-center gap-2 p-4">
      <span className="mr-1 text-[0.8125rem] font-semibold text-subheading">Your action</span>
      {forms.map(([k, label]) => (
        <Button key={k} size="sm" variant="primary" onClick={() => setForm(k)}>
          <FileText /> {label}
        </Button>
      ))}
      {actions.map((a) => {
        const s = ACTIONS[a];
        const Icon = s.icon;
        return (
          <Button key={a} size="sm" variant={s.kind === "forward" || s.kind === "approve" ? "primary" : "outline"} className={cn(s.kind === "reject" && "border-critical/40 text-critical-text")} onClick={() => setAction(a)} title={s.title}>
            <Icon /> {s.label}
          </Button>
        );
      })}
      {c.status === "PENDING_COH" && d.mggMembers === 0 && d.can.actions.includes("COH_FORWARD") && (
        <span className="text-[0.78125rem] text-warning-text">No {MGG} account is authorised yet – ask the admin.</span>
      )}
      <Dialog open={form !== null} onOpenChange={(o) => !o && setForm(null)}>
        <DialogContent className="max-h-[88vh] overflow-y-auto">
          {form && (
            <CaseForm
              d={d}
              kind={form}
              onCancel={() => setForm(null)}
              onDone={(text) => {
                setForm(null);
                onChanged({ ok: true, text });
              }}
            />
          )}
        </DialogContent>
      </Dialog>
      <Dialog open={action !== null} onOpenChange={(o) => !o && setAction(null)}>
        <DialogContent className="max-h-[88vh] overflow-y-auto">
          {action && (
            <ActionForm
              d={d}
              action={action}
              onCancel={() => setAction(null)}
              onDone={(text) => {
                setAction(null);
                onChanged({ ok: true, text });
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}

const PHOTO_ACCEPT = ".jpg,.jpeg,.png";
const EVIDENCE_ACCEPT = ".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png";
const MAX_FILES = 10;

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-[0.8125rem] font-medium">
        {label}
        {required && <span className="text-critical-text"> *</span>}
      </span>
      {children}
    </label>
  );
}

function FilePick({ label, accept, files, setFiles, disabled }: { label: string; accept: string; files: File[]; setFiles: (f: File[]) => void; disabled: boolean }) {
  return (
    <div className="space-y-1">
      <span className="text-[0.8125rem] font-medium">{label}</span>
      <input
        type="file"
        multiple
        accept={accept}
        disabled={disabled}
        onChange={(e) => {
          setFiles([...files, ...Array.from(e.target.files ?? [])].slice(0, MAX_FILES));
          e.target.value = "";
        }}
        className="block w-full text-[0.78125rem] file:mr-3 file:rounded-md file:border-0 file:bg-primary-soft file:px-3 file:py-1.5 file:text-[0.78125rem] file:font-semibold file:text-primary"
        aria-label={label}
      />
      {files.length > 0 && (
        <ul className="space-y-0.5 text-[0.75rem]">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-1">
              <span className="min-w-0 flex-1 truncate">
                {f.name} <span className="text-muted-foreground">({fileSize(f.size)})</span>
              </span>
              <button type="button" disabled={disabled} onClick={() => setFiles(files.filter((_, j) => j !== i))} className="rounded p-0.5 hover:bg-accent" aria-label={`Remove ${f.name}`}>
                <X className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const FORM_META: Record<FormKind, { title: string; desc: string }> = {
  verify: { title: "E1 – Physical verification", desc: "Record the visit of the GP site. Attach the evidence and site photographs." },
  justify: { title: "E2 – Justification to the Area Manager", desc: "Explain why the GP is not doable, with the FRT team and visit details. The case goes to your Area Manager." },
  revisitCoordination: { title: "FRT coordination", desc: `After the rejection by the ${MGG}: record the coordination with the FRT team for a new site visit.` },
  revisitVisit: { title: "New FRT site visit", desc: "Record the new FRT site visit. Then review the GP in the daily progress of the ticket." },
};

function CaseForm({ d, kind, onCancel, onDone }: { d: NdCaseDetail; kind: FormKind; onCancel: () => void; onDone: (text: string) => void }) {
  const today = new Date().toLocaleDateString("en-CA");
  const [v, setV] = useState<Record<string, string>>(kind === "verify" || kind === "revisitVisit" ? { visitDate: today } : {});
  const [evidence, setEvidence] = useState<File[]>([]);
  const [photos, setPhotos] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const set = (k: string) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setV({ ...v, [k]: e.target.value });
  const val = (k: string) => (v[k] ?? "").trim();
  const hadFiles = d.records.some((r) => r.files.length > 0);
  const missing =
    kind === "verify"
      ? !val("visitDate") || val("visitorName").length < 2 || val("reason").length < 3 || val("findings").length < 3 || (!hadFiles && !evidence.length && !photos.length)
      : kind === "justify"
        ? val("justification").length < 10 || val("frtTeam").length < 3 || val("frtVisit").length < 3
        : kind === "revisitCoordination"
          ? val("frtTeam").length < 3 || val("remarks").length < 3
          : !val("visitDate") || val("visitorName").length < 2 || val("findings").length < 3 || !val("outcome");
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      const api = { verify: "verification", justify: "justification", revisitCoordination: "revisit", revisitVisit: "revisit" } as const;
      const data = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, x.trim()]));
      await ndApi.submitForm(d.case.id, api[kind], data, { evidence, photos }, kind === "revisitCoordination" ? "COORDINATION" : kind === "revisitVisit" ? "VISIT" : undefined, setProgress);
      onDone(`${FORM_META[kind].title} saved for ${d.case.ref}. Everyone concerned has been notified.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the form");
      setBusy(false);
    }
  };
  const area = (k: string, rows = 3, ph = "") => <textarea value={v[k] ?? ""} onChange={set(k)} rows={rows} maxLength={2000} className={TEXTAREA} placeholder={ph} disabled={busy} />;
  return (
    <form
      className="space-y-4 p-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!missing && !busy) void send();
      }}
    >
      <div>
        <DialogTitle className="text-lg font-bold">{FORM_META[kind].title}</DialogTitle>
        <DialogDescription className="mt-1 text-sm text-muted-foreground">
          {d.case.ref} · GP {d.gp.gpCode} – {d.gp.gpName}. {FORM_META[kind].desc}
        </DialogDescription>
      </div>
      {(kind === "verify" || kind === "revisitVisit") && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={kind === "verify" ? "Physical visit date" : "FRT visit date"} required>
            <Input type="date" value={v.visitDate ?? ""} max={today} onChange={set("visitDate")} className="h-9" disabled={busy} />
          </Field>
          <Field label={kind === "verify" ? "Visitor name" : "FRT visitor name"} required>
            <Input value={v.visitorName ?? ""} onChange={set("visitorName")} maxLength={160} className="h-9" disabled={busy} />
          </Field>
          <Field label="GP location (coordinates / landmark)">
            <Input value={v.location ?? ""} onChange={set("location")} maxLength={300} className="h-9" disabled={busy} />
          </Field>
        </div>
      )}
      {kind === "verify" && (
        <>
          <Field label="Non-Doable reason" required>
            {area("reason", 2, "Why the GP cannot be done…")}
          </Field>
          <Field label="Findings" required>
            {area("findings", 3, "What was found on site…")}
          </Field>
        </>
      )}
      {kind === "justify" && (
        <>
          <Field label="Justification" required>
            {area("justification", 4, "Detailed justification (at least 10 characters)…")}
          </Field>
          <Field label="FRT team details" required>
            {area("frtTeam", 2, "FRT team, lead and contact…")}
          </Field>
          <Field label="FRT visit details" required>
            {area("frtVisit", 2, "When the FRT visited and what they confirmed…")}
          </Field>
        </>
      )}
      {kind === "revisitCoordination" && (
        <Field label="FRT team details" required>
          {area("frtTeam", 2, "FRT team, lead and contact…")}
        </Field>
      )}
      {kind === "revisitVisit" && (
        <>
          <Field label="Findings of the FRT visit" required>
            {area("findings", 3)}
          </Field>
          <Field label="Outcome of the FRT visit" required>
            <Select
              ariaLabel="Outcome of the FRT visit"
              value={v.outcome || undefined}
              onValueChange={(x) => setV({ ...v, outcome: x ?? "" })}
              placeholder="Choose…"
              options={[
                { value: "A", label: CATEGORY.A.label },
                { value: "C", label: CATEGORY.C.label },
                { value: "D", label: CATEGORY.D.label },
              ]}
              className="w-full"
            />
          </Field>
        </>
      )}
      <Field label={kind === "revisitCoordination" ? "Coordination details" : "Remarks"} required={kind === "revisitCoordination"}>
        {area("remarks", 2)}
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <FilePick label={kind === "justify" ? "Additional evidence" : "Evidence documents"} accept={EVIDENCE_ACCEPT} files={evidence} setFiles={setEvidence} disabled={busy} />
        <FilePick label="Site photographs (JPEG / PNG)" accept={PHOTO_ACCEPT} files={photos} setFiles={setPhotos} disabled={busy} />
      </div>
      {kind === "verify" && !hadFiles && <p className="text-[0.75rem] text-muted-foreground">At least one evidence document or site photograph is required.</p>}
      {busy && progress > 0 && progress < 1 && <p className="text-[0.75rem] text-muted-foreground">Uploading… {Math.round(progress * 100)}%</p>}
      {error && (
        <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={busy || missing}>
          {busy && <Loader2 className="animate-spin" />} Submit
        </Button>
      </div>
    </form>
  );
}

function ActionForm({ d, action, onCancel, onDone }: { d: NdCaseDetail; action: NdAction; onCancel: () => void; onDone: (text: string) => void }) {
  const s = ACTIONS[action];
  const [remark, setRemark] = useState("");
  const [target, setTarget] = useState<"" | "FE" | "AM" | "SME">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [typed, setTyped] = useState<Typed[]>([]);
  const toRole = s.to ?? null;
  const q = useApiQuery(toRole ? `nd-contacts:${d.case.id}:${toRole}` : null, () => ndApi.getContacts(d.case.id, toRole ?? "SME"));
  const [seeded, setSeeded] = useState<ReviewContacts | null>(null);
  if (q.data && seeded !== q.data) {
    // pre-select: who is already on the ticket, else every matrix person's first e-mail
    const c = q.data;
    const on: Record<string, string> = {};
    for (const p of c.people) for (const e of p.emails) if (e.onTicket) on[e.email] = p.name;
    for (const r of c.onTicket) on[r.email] = r.name;
    if (!Object.keys(on).length) for (const p of c.people) if (p.emails[0]) on[p.emails[0].email] = p.name;
    setSeeded(c);
    setPicked(on);
    if (!c.people.length && !c.onTicket.length) setTyped([{ key: 1, name: "", email: "" }]);
  }
  const typedOk = typed.filter((r) => EMAIL.test(r.email.trim()));
  const typedBad = typed.some((r) => r.email.trim() !== "" && !EMAIL.test(r.email.trim()));
  const to = toRole ? [...Object.entries(picked).map(([email, name]) => ({ name, email })), ...typedOk.map((r) => ({ name: r.name.trim() || undefined, email: r.email.trim() }))] : [];
  const needsText = s.kind !== "approve" && s.kind !== "withdraw";
  const isReason = s.kind === "return" || s.kind === "reject";
  const short = needsText && remark.trim().length < 3;
  const noTo = toRole !== null && to.length === 0;
  const noTarget = action === "COH_RETURN" && !target;
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      const text = remark.trim() || undefined;
      await ndApi.act(d.case.id, { action, ...(isReason ? { reason: text } : { remark: text }), ...(target ? { target } : {}), ...(toRole ? { to } : {}) });
      const whom = toRole ? ` E-mail sent to ${to.map((x) => x.email).join(", ")}.` : "";
      onDone(`${d.case.ref}: ${s.title} – done. Everyone concerned has been notified.${whom}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the step");
      setBusy(false);
    }
  };
  return (
    <form
      className="space-y-4 p-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy && !short && !noTo && !noTarget && !typedBad) void send();
      }}
    >
      <div>
        <DialogTitle className="text-lg font-bold">{s.title}</DialogTitle>
        <DialogDescription className="mt-1 text-sm text-muted-foreground">
          {d.case.ref} · GP {d.gp.gpCode} – {d.gp.gpName}
          {action === "MGG_APPROVE" && " – the GP is closed as Non-Doable and can no longer change in the daily progress."}
          {action === "MGG_REJECT" && " – the GP goes back to Revisit Required: the FE coordinates with the FRT team for a new site visit."}
        </DialogDescription>
      </div>
      {action === "COH_RETURN" && (
        <Field label="Return to" required>
          <Select
            ariaLabel="Return to"
            value={target || undefined}
            onValueChange={(x) => setTarget((x ?? "") as "" | "FE" | "AM" | "SME")}
            placeholder="Choose…"
            options={[
              { value: "FE", label: "Field Engineer (verification / justification)" },
              { value: "AM", label: "Area Manager" },
              { value: "SME", label: "SME" },
            ]}
            className="w-full"
          />
        </Field>
      )}
      {toRole && <SendTo role={toRole} contacts={q.data} loading={q.loading} failed={!!q.error} picked={picked} setPicked={setPicked} typed={typed} setTyped={setTyped} disabled={busy} />}
      <Field label={isReason ? (action === "MGG_REJECT" ? "Rejection reason" : "Reason for returning") : s.kind === "forward" ? "Recommendation / remarks" : "Remarks (optional)"} required={needsText}>
        <textarea value={remark} onChange={(e) => setRemark(e.target.value)} rows={3} maxLength={2000} className={TEXTAREA} disabled={busy} />
      </Field>
      {error && (
        <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={busy || short || noTo || noTarget || typedBad} title={noTo ? `Choose or type the ${toRole} e-mail` : undefined}>
          {busy && <Loader2 className="animate-spin" />} {s.label}
        </Button>
      </div>
    </form>
  );
}

/* ---------------------------------------------------------------- forms, evidence and history */

const RECORD_TITLE: Record<NdRecord["kind"], string> = {
  VERIFICATION: "E1 – Physical verification",
  JUSTIFICATION: "E2 – Justification",
  REVISIT_COORDINATION: "Revisit – FRT coordination",
  REVISIT_VISIT: "Revisit – New FRT site visit",
};

function Records({ records }: { records: NdRecord[] }) {
  return (
    <Card className="space-y-3 p-5">
      <h3 className="text-[0.9375rem] font-bold text-heading">Verification, justification and evidence</h3>
      {records.length === 0 ? (
        <p className="text-[0.8125rem] text-muted-foreground">No form submitted yet.</p>
      ) : (
        records.map((r) => (
          <article key={r.id} className="space-y-2 rounded-lg border border-border p-3 text-[0.8125rem]">
            <header className="flex flex-wrap items-baseline justify-between gap-2">
              <b className="font-semibold">{RECORD_TITLE[r.kind]}</b>
              <span className="text-[0.75rem] text-muted-foreground">
                {r.by} · {ticketTime(r.at)}
              </span>
            </header>
            <dl className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
              {r.visitDate && <Info k="Visit date" v={ticketDay(r.visitDate)} />}
              {r.visitorName && <Info k="Visitor" v={r.visitorName} />}
              {r.location && <Info k="GP location" v={r.location} />}
              {r.outcome && <Info k="FRT outcome" v={CATEGORY[r.outcome].label} />}
            </dl>
            {(
              [
                ["Non-Doable reason", r.reason],
                ["Findings", r.findings],
                ["Justification", r.justification],
                ["FRT team", r.frtTeam],
                ["FRT visit", r.frtVisit],
                ["Remarks", r.remarks],
              ] as [string, string | null][]
            )
              .filter(([, x]) => x)
              .map(([k, x]) => (
                <p key={k} className="whitespace-pre-wrap">
                  <span className="text-[0.71875rem] font-semibold uppercase tracking-wide text-muted-foreground">{k}: </span>
                  {x}
                </p>
              ))}
            {r.files.length > 0 && <FileList files={r.files} />}
          </article>
        ))
      )}
    </Card>
  );
}

function FileList({ files }: { files: NdFile[] }) {
  return (
    <ul className="space-y-1">
      {files.map((f) => (
        <li key={f.id} className="flex flex-wrap items-center gap-2 text-[0.78125rem]">
          <span className={cn("rounded px-1.5 py-0.5 text-[0.65625rem] font-semibold", f.kind === "PHOTO" ? "bg-primary-soft text-primary" : "bg-muted text-foreground")}>{f.kind === "PHOTO" ? "Photo" : "Evidence"}</span>
          <span className="min-w-0 flex-1 truncate" title={f.fileName}>
            {f.fileName} <span className="text-muted-foreground">({fileSize(f.size)})</span>
          </span>
          {f.previewable && (
            <a href={ndApi.fileUrl(f.id, true)} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
              <Eye className="size-3.5" /> Preview
            </a>
          )}
          <a href={ndApi.fileUrl(f.id)} className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
            <Download className="size-3.5" /> Download
          </a>
        </li>
      ))}
    </ul>
  );
}

function History({ d }: { d: NdCaseDetail }) {
  return (
    <Card className="space-y-3 p-5">
      <h3 className="text-[0.9375rem] font-bold text-heading">History</h3>
      <ol className="space-y-2.5 border-l border-border pl-3">
        {[...d.history].reverse().map((e) => (
          <li key={e.id} className="text-[0.8125rem]">
            <span className="flex flex-wrap items-baseline gap-x-2">
              <span className="rounded bg-muted px-1.5 py-0.5 text-[0.65625rem] font-bold">{e.stage}</span>
              <b className="font-semibold">{e.label}</b>
            </span>
            <span className="block text-[0.75rem] text-muted-foreground">
              {e.roleLabel} {e.by} · {ticketTime(e.at)}
            </span>
            {e.fromLabel !== e.toLabel && e.toLabel && (
              <span className="block text-[0.75rem]">
                {e.fromLabel ?? "—"} → <b className="font-semibold">{e.toLabel}</b>
              </span>
            )}
            {e.recommendation && <span className="block text-[0.78125rem]">Recommendation: {e.recommendation}</span>}
            {e.reason && <span className="block text-[0.78125rem] text-critical-text">Reason: {e.reason}</span>}
            {e.remark && <span className="block text-[0.78125rem] text-foreground/85">{e.remark}</span>}
          </li>
        ))}
      </ol>
      {d.history.length === 0 && (
        <p className="flex items-center gap-2 text-[0.8125rem] text-muted-foreground">
          <Ban className="size-4" /> No history yet.
        </p>
      )}
    </Card>
  );
}
