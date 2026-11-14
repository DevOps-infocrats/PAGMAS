"use client";

import { CircleCheck, ClipboardList, Timer } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { MiniKpi } from "@/components/kpi/mini-kpi";
import { PageHeader } from "@/components/layout/page-header";
import { Select } from "@/components/ui/overlays";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useSession } from "@/hooks/use-session";
import { IS_LIVE, ticketApi, type TicketDetail, type TicketKpis } from "@/lib/api";
import { formatCount } from "@/lib/utils/format";
import {
  ActivityLog,
  BackToList,
  CODE_COL,
  CREATED_COL,
  EMPTY_FILTERS,
  FeedbackCallout,
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
  type ListFilters,
  type Notice,
  type TicketColumn,
} from "./ticket-parts";
import { RecipientsCard } from "./ticket-recipients";
import { ShareCard } from "./ticket-share";
import { TaskPanel } from "./ticket-task";
import { WorkSubmission } from "./work-submission";

const day = (iso: string, withMonth: boolean) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "2-digit", ...(withMonth ? { month: "short" } : {}), timeZone: "UTC" });
/** "Week 46 · 07–13 Nov" (dates of the task week) */
export function weekLabel(id: string, start?: string | null, end?: string | null): string {
  const n = id.replace("W-", "Week ");
  if (!start || !end) return n;
  const sameMonth = start.slice(0, 7) === end.slice(0, 7);
  return `${n} · ${sameMonth ? day(start, false) : day(start, true)}–${day(end, true)}`;
}

const COLUMNS: TicketColumn[] = [
  CODE_COL,
  {
    key: "week",
    header: "Week",
    render: (t) => (t.week ? <span className="whitespace-nowrap font-medium">{weekLabel(t.week, t.weekStart, t.weekEnd)}</span> : <span className="text-muted-foreground">—</span>),
  },
  { key: "am", header: "Area Manager", render: (t) => <span className="whitespace-nowrap">{t.areaManager ?? <span className="text-muted-foreground">—</span>}</span> },
  SUBJECT_COL,
  PRIORITY_COL,
  { key: "by", header: "Assigned By", render: (t) => <span className="whitespace-nowrap">{t.createdBy.name}</span> },
  CREATED_COL,
  STATUS_COL,
];
const ALL_WEEKS = "all";

export function UserTicketsView() {
  const { session } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const openId = ticketIdFrom(params.get("ticket"));
  const [tick, setTick] = useState(0);
  const [notice, setNotice] = useState<Notice>(null);
  const open = useCallback((id: number | null) => router.push(id ? `${pathname}?ticket=${id}` : pathname, { scroll: true }), [router, pathname]);

  if (!session) return <PageSkeleton />;
  if (!IS_LIVE)
    return (
      <Card className="p-6 text-sm text-muted-foreground">
        Ticket Management needs the live backend (NEXT_PUBLIC_API_MODE=live).
      </Card>
    );

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Ticket Management" }, { label: "User Tickets", href: pathname }, ...(openId ? [{ label: "Ticket details" }] : [])]}
        title="User Tickets"
        description="Tickets assigned to you: do the work, upload your documents and submit it for the admin's review."
        actions={openId ? <BackToList onBack={() => open(null)} label="Back to my tickets" /> : undefined}
      />
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
      {openId ? (
        <UserTicketDetail
          id={openId}
          tick={tick}
          onChanged={(n) => {
            setNotice(n);
            setTick((x) => x + 1);
          }}
        />
      ) : (
        <UserTicketList tick={tick} onOpen={(id) => open(id)} />
      )}
    </div>
  );
}

function UserKpis({ k }: { k?: TicketKpis }) {
  const L = !k;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <MiniKpi
        loading={L}
        icon={ClipboardList}
        tone="var(--series-1)"
        label="Total Assigned Tickets"
        info="Every ticket assigned to your account, in any status."
        value={formatCount(k?.total)}
        unit="tickets"
        caption={k ? `${formatCount(k.byStatus.OPEN)} open · ${formatCount(k.byStatus.PENDING_REVIEW)} pending review · ${formatCount(k.byStatus.CHANGES_REQUESTED)} changes requested` : undefined}
      />
      <MiniKpi
        loading={L}
        icon={Timer}
        tone="var(--warning)"
        label="Working Tickets"
        info="Tickets you have started (In Progress) and not yet submitted."
        value={formatCount(k?.working)}
        unit="tickets"
        caption="Status: In Progress"
      />
      <MiniKpi
        loading={L}
        icon={CircleCheck}
        tone="var(--good)"
        label="Closed Tickets"
        info="Tickets the admin approved and closed. Closed tickets are read-only."
        value={formatCount(k?.closed)}
        unit="tickets"
        caption="Approved by the admin"
      />
    </div>
  );
}

function UserTicketList({ tick, onOpen }: { tick: number; onOpen: (id: number) => void }) {
  const [filters, setFilters] = useState<ListFilters>(EMPTY_FILTERS);
  // week filter: the latest week of the user's GP-wise tickets by default (null = not chosen yet), or every week
  const [chosenWeek, setChosenWeek] = useState<string | null>(null);
  const weeksQ = useApiQuery(`tickets-weeks:mine:${tick}`, () => ticketApi.myWeeks());
  const weeks = weeksQ.data?.weeks ?? [];
  const week = chosenWeek ?? (weeksQ.data ? (weeks[0]?.id ?? ALL_WEEKS) : weeksQ.error ? ALL_WEEKS : null);
  const q = { ...listQuery(filters), week: week && week !== ALL_WEEKS ? week : undefined };
  const kpis = useApiQuery(`tickets-kpis:mine:${tick}`, () => ticketApi.getKpis("mine"));
  // wait for the weeks (the default week) before the first list request
  const list = useApiQuery(week === null ? null : `tickets:mine:${tick}:${JSON.stringify(q)}`, () => ticketApi.list({ scope: "mine", ...q }));
  const filtered = !!(filters.search || filters.status !== "all" || filters.priority !== "all" || (week && week !== ALL_WEEKS));
  const openElsewhere = week && week !== ALL_WEEKS ? weeks.filter((w) => w.id !== week).reduce((n, w) => n + w.open, 0) : 0;
  return (
    <>
      {kpis.error ? (
        <Card>
          <ErrorState error={kpis.error} onRetry={kpis.reload} />
        </Card>
      ) : (
        <UserKpis k={kpis.data} />
      )}
      <TicketTable
        title="Tickets assigned to or shared with you"
        page={list.data ?? list.staleData}
        error={list.error}
        loading={list.loading || week === null}
        onRetry={list.reload}
        columns={COLUMNS}
        onOpen={(t) => onOpen(t.id)}
        onPage={(page) => setFilters((f) => ({ ...f, page }))}
        filtered={filtered}
        emptyText="When an admin assigns a ticket to you it appears here."
        filters={
          <>
            <TicketFilterBar
              value={filters}
              onChange={setFilters}
              searchHint="Ticket ID or subject"
              extra={
                weeks.length > 0 ? (
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="text-xs font-semibold text-foreground/75">Week</span>
                    <Select
                      ariaLabel="Week"
                      value={week ?? ALL_WEEKS}
                      onValueChange={(v) => {
                        if (!v) return;
                        setChosenWeek(v);
                        setFilters((f) => ({ ...f, page: 1 }));
                      }}
                      options={[
                        ...weeks.map((w, i) => ({ value: w.id, label: `${weekLabel(w.id, w.start, w.end)} · ${w.total} ticket${w.total === 1 ? "" : "s"}${i === 0 ? " · latest" : ""}` })),
                        { value: ALL_WEEKS, label: "All weeks" },
                      ]}
                      // one line like the other filters: a long label is cut with "…" instead of wrapping out of the box
                      className="w-full min-w-0 [&>span:first-child]:truncate"
                    />
                  </div>
                ) : null
              }
            />
            {openElsewhere > 0 && (
              <div className="flex items-center justify-between gap-3 border-b border-border bg-warning-soft/50 px-4 py-2 text-[0.78125rem] text-warning-text">
                <span>
                  {openElsewhere} open ticket{openElsewhere === 1 ? "" : "s"} in other weeks.
                </span>
                <button type="button" onClick={() => setChosenWeek(ALL_WEEKS)} className="shrink-0 rounded px-2 py-0.5 font-semibold hover:bg-warning-soft">
                  Show all weeks
                </button>
              </div>
            )}
          </>
        }
      />
    </>
  );
}

const MY_ROLE: Record<Exclude<TicketDetail["myRole"], null | "ASSIGNEE">, string> = {
  AM: "Area Manager",
  FE: "FE",
  SME: "SME",
  COH: "COH",
  CBH: "CBH",
  USER: "Dashboard user",
  OTHER: "Recipient",
};

function UserTicketDetail({ id, tick, onChanged }: { id: number; tick: number; onChanged: (n: Notice) => void }) {
  const { session } = useSession();
  const [local, setLocal] = useState<TicketDetail | null>(null);
  const q = useApiQuery(`ticket:${id}:${tick}`, () => ticketApi.get(id));
  const t = local && local.id === id && !q.data ? local : (q.data ?? local);
  if (q.error) return <Card><ErrorState error={q.error} onRetry={q.reload} /></Card>;
  if (!t || t.id !== id) return <PageSkeleton />;
  const role = t.myRole ? (t.myRole === "ASSIGNEE" ? (t.task ? "Area Manager" : "Assignee") : MY_ROLE[t.myRole]) : null;
  const reviewer = (t.myRole === "SME" || t.myRole === "COH") && (t.can.reviewAs?.length ?? 0) > 0;
  return (
    <div className="space-y-5">
      {session && role && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-primary/25 bg-primary-soft/40 px-4 py-2.5">
          <span className="text-[0.9375rem] font-bold text-heading">
            {session.name} <span className="font-semibold text-primary">({role})</span>
          </span>
          {t.task && (
            <span className="text-[0.8125rem] text-muted-foreground">
              {t.myRole === "FE" ? (
                <>
                  Area Manager <b className="font-semibold text-foreground">{t.task.areaManager}</b>
                </>
              ) : t.myRole === "AM" || t.myRole === "ASSIGNEE" ? (
                <>
                  {(t.task.fes ?? []).filter((f) => f.name).length} Field Engineer{(t.task.fes ?? []).filter((f) => f.name).length === 1 ? "" : "s"} under you
                </>
              ) : (
                <>
                  Area Manager <b className="font-semibold text-foreground">{t.task.areaManager}</b>
                </>
              )}
              {t.task.circle && <> · {t.task.circle}</>} · {t.task.week.id.replace("W-", "Week ")}
            </span>
          )}
        </div>
      )}
      <TicketInfo t={t} showAssignee={false} />
      {reviewer && t.status !== "CLOSED" && (
        <p role="note" className="rounded-lg border border-border bg-muted/40 px-4 py-2.5 text-[0.8125rem] text-muted-foreground">
          {t.myRole === "SME"
            ? "Review the GPs the Area Manager approved (details, FE remarks, photos, AM remarks and approval date), then forward them to the COH with your remarks and the confirmed category – or send a GP back to the AM with the reason if you find an issue."
            : "Record the letter submission and the AMC conversion of the GPs the SME forwarded – or send a GP back to the SME with the reason if you find an issue."}
        </p>
      )}
      {(t.myRole === "CBH" || t.myRole === "USER" || ((t.myRole === "SME" || t.myRole === "COH") && !reviewer)) && !t.can.start && !t.can.submit && !t.can.progress && t.status !== "CLOSED" && (
        <p role="note" className="rounded-lg border border-border bg-muted/40 px-4 py-2.5 text-[0.8125rem] text-muted-foreground">
          This ticket is shared with you for monitoring (view only){t.task ? ` – ${t.task.areaManager} reports the daily GP progress` : ""}. Only the admin can close it.
        </p>
      )}
      <FeedbackCallout t={t} />
      {t.task && (
        <TaskPanel
          t={t}
          admin={false}
          onChanged={(next, n) => {
            setLocal(next);
            onChanged(n);
          }}
        />
      )}
      {t.task && t.can.share && (
        <ShareCard
          t={t}
          onChanged={(next, n) => {
            setLocal(next);
            onChanged(n);
          }}
        />
      )}
      <WorkSubmission
        t={t}
        onChanged={(next, n) => {
          setLocal(next);
          onChanged(n);
        }}
      />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <SubmissionHistory t={t} emptyText="Nothing submitted yet." />
        <div className="space-y-5">
          <RecipientsCard t={t} />
          <ActivityLog t={t} />
        </div>
      </div>
    </div>
  );
}
