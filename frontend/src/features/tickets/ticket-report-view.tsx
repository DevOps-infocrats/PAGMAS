"use client";

import { Ban, CalendarCheck, CheckCircle2, FileSpreadsheet, Loader2, Search, Send, ShieldCheck, Target, Ticket } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/feedback/states";
import { MiniKpi } from "@/components/kpi/mini-kpi";
import { AdminGuard } from "@/components/layout/admin-guard";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { IS_LIVE, ticketApi, type TicketReport } from "@/lib/api";
import { API_BASE } from "@/lib/api/http-client";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";

/**
 * Ticket Report (admin, read only – backend app.tickets.report). Tickets are generated once a week (BSNL week,
 * Saturday – Friday); the Daily Achievement is submitted every day. Three parts:
 *   1. the week at a glance (cards)
 *   2. the team tracker – AM / FE / FRT: who got how many tickets and GPs, and who submitted on which day
 *   3. what was completed this week, who and when (+ SME / COH reviews and the week-by-week trend)
 */
export function TicketReportView() {
  return (
    <AdminGuard>
      <ReportContent />
    </AdminGuard>
  );
}

type Person = TicketReport["people"][number];
type Day = TicketReport["days"][number];

const ALL = "__all";
const TABS = ["AM", "FE", "FRT"] as const;
const ROLE_LABEL: Record<string, string> = { AM: "Area Managers", FE: "Field Engineers", FRT: "FRT teams", SME: "SME", COH: "COH" };
const WHAT: Record<TicketReport["completed"][number]["what"], { label: string; cls: string }> = {
  DONE: { label: "Done", cls: "bg-good-soft text-good-text" },
  LETTER_SUBMITTED: { label: "Letter submitted (done)", cls: "bg-good-soft text-good-text" },
  AMC_CONVERTED: { label: "AMC converted", cls: "bg-primary-soft text-primary" },
  ND_APPROVED: { label: "Non-Doable approved", cls: "bg-warning-soft text-warning-text" },
};
const dayHead = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`);
  return { wd: d.toLocaleDateString("en-IN", { weekday: "short" }), dm: d.toLocaleDateString("en-IN", { day: "2-digit", month: "short" }) };
};
const fmtDate = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
const fmtTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");

/** GP status (the Daily Achievement category), in the order of the work */
const STATUS: { key: "A" | "B" | "E" | "C" | "D" | "none"; label: string; color: string }[] = [
  { key: "A", label: "Rectification Done", color: "var(--good)" },
  { key: "B", label: "Ready for Letter", color: "var(--series-3)" },
  { key: "E", label: "Letter Submitted", color: "var(--series-7)" },
  { key: "C", label: "Revisit Required", color: "var(--warning)" },
  { key: "D", label: "Non-Doable", color: "var(--critical)" },
  { key: "none", label: "Not filled", color: "color-mix(in srgb, var(--muted-foreground) 35%, transparent)" },
];

/** Thin stacked bar of a status breakdown; hover = the counts. */
function StatusBar({ s, wide = false }: { s?: Record<string, number>; wide?: boolean }) {
  const total = STATUS.reduce((n, x) => n + (s?.[x.key] ?? 0), 0);
  if (!s || !total) return <span className="text-[0.75rem] text-muted-foreground">—</span>;
  const title = STATUS.filter((x) => s[x.key]).map((x) => `${x.label} ${s[x.key]}`).join(" · ");
  return (
    <span className={cn("flex overflow-hidden rounded-full bg-muted", wide ? "h-3 w-full" : "h-2.5 w-32")} title={title} role="img" aria-label={title}>
      {STATUS.map((x) => (s[x.key] ? <span key={x.key} style={{ width: `${(s[x.key] / total) * 100}%`, background: x.color }} /> : null))}
    </span>
  );
}

/** "today" / "yesterday" / "3 days ago" / a date */
const ago = (iso: string | null | undefined, today: string) => {
  if (!iso) return null;
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-CA");
  const diff = Math.round((new Date(`${today}T00:00:00`).getTime() - new Date(`${day}T00:00:00`).getTime()) / 86400000);
  return diff <= 0 ? "today" : diff === 1 ? "yesterday" : diff < 30 ? `${diff} days ago` : fmtDate(day);
};

/** The days a person was expected to work: with GPs, a login and their ticket on that day; past days, and today only
 * once something was done (today is not over – it never counts as missed). */
const workDays = (p: Person, days: Day[], today: string) =>
  p.account && p.gps > 0
    ? days.filter((d) => !d.future && (!p.loginSince || d.date >= p.loginSince) && (!p.ticketSince || d.date >= p.ticketSince) && (d.date < today || !!p.days[d.date]))
    : [];

/** "3 submitted · 2 verified · 1 returned" – what a person did on a day */
const dayText = (c: Person["days"][string]) =>
  [c.subs ? `submitted ${c.gps} GP${c.gps === 1 ? "" : "s"}${c.done ? ` (${c.done} done)` : ""}` : "", ...Object.entries(c.acts ?? {}).map(([k, n]) => `${n} ${k}`)].filter(Boolean).join(" · ");

function ReportContent() {
  const [week, setWeek] = useState<string | undefined>();
  const [circle, setCircle] = useState(ALL);
  const [tab, setTab] = useState<Tab>("AM"); // the team tracker's role (also picked from the "Tickets for" cards)
  // the section tab – kept in the address (?tab=…) so a refresh or a shared link opens the same one
  const [section, setSection] = useState<Section>("team");
  useEffect(() => {
    try {
      const t = new URLSearchParams(window.location.search).get("tab");
      if (t && (SECTIONS as readonly string[]).includes(t)) setSection(t as Section); // eslint-disable-line react-hooks/set-state-in-effect -- read once from the address
    } catch {
      /* no address access – the default tab */
    }
  }, []);
  const pickSection = (s: Section) => {
    setSection(s);
    try {
      const u = new URL(window.location.href);
      if (s === "team") u.searchParams.delete("tab");
      else u.searchParams.set("tab", s);
      window.history.replaceState(window.history.state, "", u);
    } catch {
      /* the tab still switches */
    }
  };
  const q = useApiQuery(IS_LIVE ? `ticket-report:${week ?? ""}:${circle}` : null, () => ticketApi.getTicketReport({ week, circle: circle === ALL ? undefined : circle }));
  const [busy, setBusy] = useState(false);
  const [dlError, setDlError] = useState<string | null>(null);
  const r = q.data;

  /** Excel: fetched in the page and saved from a blob (works on the self-signed HTTPS site too) */
  const download = async () => {
    setBusy(true);
    setDlError(null);
    try {
      const params = new URLSearchParams();
      if (r?.week) params.set("week", r.week.code);
      if (circle !== ALL) params.set("circle", circle);
      const res = await fetch(`${API_BASE}/tickets/report.xlsx?${params}`, { credentials: "same-origin", cache: "no-store" });
      if (!res.ok) throw new Error(`Excel download failed (${res.status})`);
      const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "Ticket_Report.xlsx";
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setDlError(e instanceof Error ? e.message : "Excel download failed");
    } finally {
      setBusy(false);
    }
  };

  const inWeek = !!r?.days.some((d) => d.date === r.today);
  const sections: { key: Section; label: string; count?: number }[] = [
    { key: "team", label: "Team tracker" },
    { key: "pending", label: "Pending with", count: r?.pending?.buckets.reduce((n, b) => n + (b.key === "closed" ? 0 : b.count), 0) },
    { key: "achievement", label: "Achievement" },
    { key: "returns", label: "Returns", count: r?.returns?.items.length },
    { key: "completed", label: "Completed & reviews", count: r ? (r.completedTotal ?? r.completed.length) : undefined },
  ];
  return (
    <>
      <PageHeader
        title="Ticket Report"
        description="Weekly tracking of the GP-wise tickets: who got tickets this week, who submits the Daily Achievement every day, and what was completed."
        breadcrumbs={[{ label: "Ticket Management" }, { label: "Admin Tickets", href: "/dashboard/tickets/admin" }, { label: "Ticket Report" }]}
        actions={
          <Button variant="outline" onClick={download} disabled={busy || !r?.week}>
            {busy ? <Loader2 className="animate-spin" /> : <FileSpreadsheet />} Download Excel
          </Button>
        }
      />
      {!IS_LIVE && <Card className="p-5 text-sm text-muted-foreground">The Ticket Report needs the backend connected.</Card>}
      {q.error && <ErrorState error={q.error} onRetry={q.reload} />}
      {IS_LIVE && !r && !q.error && <PageSkeleton />}
      {dlError && <p className="mb-3 rounded-lg border border-critical/40 bg-critical-soft px-4 py-2 text-sm text-critical-text">{dlError}</p>}
      {r && !r.week && (
        <Card>
          <EmptyState icon={Ticket} title="No ticket week yet" description="Generate GP-wise task tickets in Admin Tickets – their weeks appear here." />
        </Card>
      )}
      {r?.week && r.cards && (
        <div className="space-y-5">
          <Card className="flex flex-wrap items-center gap-3 p-4">
            <span className="text-[0.8125rem] font-semibold text-subheading">Week</span>
            <Select
              ariaLabel="Ticket week"
              value={r.week.code}
              onValueChange={(v) => setWeek(v)}
              options={r.weeks.map((w) => ({ value: w.code, label: `${w.code} · ${fmtDate(w.start)} – ${fmtDate(w.end)} · ${w.tickets} ticket${w.tickets === 1 ? "" : "s"}` }))}
              className="min-w-[17rem]"
            />
            <span className="text-[0.8125rem] font-semibold text-subheading">Circle</span>
            <Select
              ariaLabel="Circle"
              value={circle}
              onValueChange={setCircle}
              options={[{ value: ALL, label: "All circles" }, ...r.circles.map((c) => ({ value: c, label: c }))]}
              className="min-w-[11rem]"
            />
            <span className="text-[0.75rem] text-muted-foreground">
              Saturday {fmtDate(r.week.start)} – Friday {fmtDate(r.week.end)}
            </span>
          </Card>

          {/* 1. the week at a glance */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <MiniKpi icon={Target} tone="var(--series-7)" label="Total GP Target for the Week" info="GPs in this week's tickets" value={formatCount(r.cards.gps)} unit="GPs" />
            <MiniKpi icon={CheckCircle2} tone="var(--good)" label="Ready for Letter Submission" info="GPs of this week's tickets that are achieved – ready for the letter submission" value={formatCount(r.cards.done)} unit="GPs" />
            <MiniKpi icon={CalendarCheck} tone="var(--series-3)" label="AMC converted" info="GPs of this week's tickets recorded as AMC converted by the COH" value={formatCount(r.cards.amcConverted)} unit="GPs" />
            <MiniKpi icon={Ban} tone="var(--warning)" label="Non-Doable" info="Non-Doable cases on this week's tickets" value={formatCount(r.cards.nonDoable)} unit="cases" caption={r.cards.nonDoableApproved ? `${r.cards.nonDoableApproved} approved` : undefined} />
            <MiniKpi
              icon={Send}
              tone="var(--series-2)"
              label={inWeek ? "Submitted today" : "Daily submissions"}
              info="Daily Achievement submissions by AM / FE / FRT (review steps not counted)"
              value={formatCount(inWeek ? r.cards.submittedToday : r.cards.submissions)}
              unit={inWeek ? "people" : "submissions"}
              caption={inWeek ? `${formatCount(r.cards.submissions)} submissions this week` : undefined}
            />
          </div>

          {/* tickets generated for each role – how many tickets, and for how many people; a click opens the team tracker */}
          <RoleTickets
            r={r}
            active={tab}
            onPick={(t) => (setTab(t), pickSection("team"), setTimeout(() => document.getElementById("report-sections")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50))}
          />

          {/* 2. the sections as tabs – every card stays mounted (hidden when not picked), so filters and lists keep their state */}
          <div id="report-sections" className="scroll-mt-20">
            <div className="mb-4 flex gap-1 overflow-x-auto border-b border-border" role="tablist" aria-label="Report sections">
              {sections.map((s) => (
                <button
                  key={s.key}
                  id={`section-tab-${s.key}`}
                  type="button"
                  role="tab"
                  aria-selected={section === s.key}
                  aria-controls={`section-${s.key}`}
                  onClick={() => pickSection(s.key)}
                  className={cn(
                    "-mb-px shrink-0 whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-semibold transition-colors",
                    section === s.key ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {s.label}
                  {s.count !== undefined && <span className="ml-1.5 rounded-full bg-muted px-1.5 text-[0.6875rem] text-muted-foreground">{formatCount(s.count)}</span>}
                </button>
              ))}
            </div>
            <div id="section-team" role="tabpanel" aria-labelledby="section-tab-team" hidden={section !== "team"}>
              <TeamTracker r={r} tab={tab} setTab={setTab} />
            </div>
            <div id="section-pending" role="tabpanel" aria-labelledby="section-tab-pending" hidden={section !== "pending"}>
              {r.pending && <PendingWith r={r} />}
            </div>
            <div id="section-achievement" role="tabpanel" aria-labelledby="section-tab-achievement" hidden={section !== "achievement"} className="space-y-5">
              {r.amAchievement && <AmAchievement r={r} />}
              <Trend r={r} />
            </div>
            <div id="section-returns" role="tabpanel" aria-labelledby="section-tab-returns" hidden={section !== "returns"}>
              {r.returns && <Returns r={r} />}
            </div>
            <div id="section-completed" role="tabpanel" aria-labelledby="section-tab-completed" hidden={section !== "completed"} className="space-y-5">
              <Completed r={r} />
              <Reviewers r={r} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}

type Tab = (typeof TABS)[number];
const SECTIONS = ["team", "pending", "achievement", "returns", "completed"] as const;
type Section = (typeof SECTIONS)[number];

/** Tickets generated this week for the AMs / FEs / FRT teams – a click opens that role in the team tracker. */
function RoleTickets({ r, active, onPick }: { r: TicketReport; active: Tab; onPick: (t: Tab) => void }) {
  const tone: Record<Tab, string> = { AM: "var(--series-1)", FE: "var(--series-3)", FRT: "var(--series-7)" };
  const noun: Record<Tab, [string, string]> = { AM: ["AM", "AMs"], FE: ["FE", "FEs"], FRT: ["FRT team", "FRT teams"] };
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {TABS.map((t) => {
        const x = r.roles.find((y) => y.role === t);
        const people = x?.people ?? 0;
        const tickets = x?.tickets ?? 0;
        return (
          <MiniKpi
            key={t}
            icon={Ticket}
            tone={tone[t]}
            label={`Tickets generated for ${t}`}
            info={`How many ${t === "AM" ? "Area Managers" : t === "FE" ? "Field Engineers" : "FRT teams"} got tickets this week (each counted once), on how many tickets and GPs. Click to see each of them in the team tracker.`}
            value={formatCount(people)}
            unit={noun[t][people === 1 ? 0 : 1]}
            caption={
              <>
                on {formatCount(tickets)} ticket{tickets === 1 ? "" : "s"} · {formatCount(x?.gps ?? 0)} GPs
                {t === "FRT" ? ` · ${formatCount(x?.withAccount ?? 0)} with login, ${formatCount(x?.withoutAccount ?? 0)} without` : ""}
              </>
            }
            onClick={() => onPick(t)}
            active={active === t}
          />
        );
      })}
    </div>
  );
}

/** Why a person needs attention (empty = fine): login but nothing on a work day, work returned, never signed in. */
function attention(p: Person, days: Day[], today = ""): string[] {
  if (!p.account || p.gps === 0) return [];
  const out: string[] = [];
  const missed = workDays(p, days, today).filter((d) => !p.days[d.date]).length;
  if (missed) out.push(`missed ${missed} day${missed === 1 ? "" : "s"}`);
  if ((p.returns ?? 0) > 0) out.push(`returned ${p.returns}×`);
  if (!p.lastLogin) out.push("never signed in");
  return out;
}

type Box = "attention" | "all" | "login" | "today";
const LIST_MAX = 10;
const PAGE_SIZE = 25;
const personKey = (p: Person) => `${p.role}:${p.name}:${p.email ?? ""}:${(p.frtCodes ?? []).join(",")}`;

function TeamTracker({ r, tab, setTab }: { r: TicketReport; tab: Tab; setTab: (t: Tab) => void }) {
  const [box, setBox] = useState<Box>("attention");
  const [full, setFull] = useState(false);
  const [detail, setDetail] = useState<Person | null>(null);
  const role = r.roles.find((x) => x.role === tab);
  const today = r.today ?? "";
  const todayInWeek = r.days.some((d) => d.date === today);
  const people = useMemo(() => r.people.filter((p) => p.role === tab && (p.tickets > 0 || p.submissions > 0)), [r.people, tab]);
  const needs = useMemo(() => people.filter((p) => attention(p, r.days, r.today ?? "").length), [people, r.days, r.today]);
  const withLogin = people.filter((p) => p.account).length;
  const submittedToday = people.filter((p) => p.days[today]).length;
  const list = useMemo(() => {
    const pick = box === "attention" ? needs : box === "login" ? people.filter((p) => p.account) : box === "today" ? people.filter((p) => p.days[today]) : people;
    return [...pick].sort((a, b) => attention(b, r.days, r.today ?? "").length - attention(a, r.days, r.today ?? "").length || (b.status?.none ?? 0) - (a.status?.none ?? 0) || a.name.localeCompare(b.name));
  }, [box, needs, people, today, r.days, r.today]);
  const frt = tab === "FRT";
  const boxes: { key: Box; label: string; value: number; tone: string }[] = [
    { key: "all", label: ROLE_LABEL[tab], value: people.length, tone: "var(--series-1)" },
    { key: "login", label: "With login", value: withLogin, tone: "var(--good)" },
    { key: "today", label: todayInWeek ? "Active today" : "Active this week", value: todayInWeek ? submittedToday : people.filter((p) => p.activeDays > 0).length, tone: "var(--series-3)" },
    { key: "attention", label: "Need attention", value: needs.length, tone: "var(--critical)" },
  ];
  const title = { attention: "Need attention", all: `All ${ROLE_LABEL[tab]}`, login: "With login", today: todayInWeek ? "Active today" : "Active this week" }[box];

  return (
    <Card id="team-tracker" className="scroll-mt-20 overflow-hidden p-0">
      <div className="border-b border-border px-5 pt-4">
        <h2 className="text-base font-bold text-subheading">Team tracker</h2>
        <p className="text-[0.8125rem] text-muted-foreground">Who needs attention this week – the full list of each role is one click away.</p>
        <div className="mt-3 flex gap-1" role="tablist" aria-label="Role">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => (setTab(t), setBox("attention"))}
              className={cn("-mb-px border-b-2 px-4 py-2.5 text-sm font-semibold", tab === t ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}
            >
              {t} <span className="ml-1 rounded-full bg-muted px-1.5 text-[0.6875rem] text-muted-foreground">{r.people.filter((p) => p.role === t && (p.tickets > 0 || p.submissions > 0)).length}</span>
            </button>
          ))}
        </div>
      </div>

      {/* four boxes – a click filters the list below */}
      <div className="grid grid-cols-2 gap-2 border-b border-border px-5 py-3 md:grid-cols-4">
        {boxes.map((b) => (
          <button
            key={b.key}
            type="button"
            onClick={() => setBox(b.key)}
            aria-pressed={box === b.key}
            className={cn("rounded-lg border px-3 py-2 text-left transition-colors hover:bg-accent/40", box === b.key ? "border-primary bg-primary-soft/40" : "border-border")}
            style={{ borderLeft: `3px solid ${b.tone}` }}
          >
            <span className="block text-[0.71875rem] font-semibold text-muted-foreground">{b.label}</span>
            <span className="text-lg font-bold" style={{ color: b.key === "attention" && b.value ? b.tone : undefined }}>
              {formatCount(b.value)}
            </span>
          </button>
        ))}
      </div>

      {/* the role's GPs by status, one line */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border px-5 py-2 text-[0.71875rem]">
        <span className="w-28 shrink-0">
          <StatusBar s={role?.status} wide />
        </span>
        {STATUS.filter((x) => role?.status?.[x.key]).map((x) => (
          <span key={x.key} className="inline-flex items-center gap-1">
            <span className="size-2 rounded-full" style={{ background: x.color }} aria-hidden /> {x.label} <b>{formatCount(role?.status?.[x.key] ?? 0)}</b>
          </span>
        ))}
        <span className="text-muted-foreground">
          · {formatCount(role?.gps ?? 0)} GPs on {formatCount(role?.tickets ?? 0)} tickets{frt ? ` · ${formatCount(role?.withoutAccount ?? 0)} without login` : ""}
        </span>
      </div>

      <div className="flex items-center justify-between gap-2 px-5 pb-1 pt-3">
        <h3 className="text-[0.8125rem] font-semibold text-subheading">
          {title} <span className="font-normal text-muted-foreground">({list.length})</span>
        </h3>
        <Button size="sm" variant="outline" onClick={() => setFull(true)}>
          View all {people.length} →
        </Button>
      </div>
      <CompactTable rows={list.slice(0, LIST_MAX)} r={r} today={today} frt={frt} onOpen={setDetail} showReasons={box === "attention"} />
      {list.length > LIST_MAX && (
        <button type="button" onClick={() => setFull(true)} className="w-full border-t border-border px-5 py-2 text-center text-[0.8125rem] font-medium text-primary hover:bg-accent/40">
          + {list.length - LIST_MAX} more – view all
        </button>
      )}
      {!list.length && (
        <p className="px-5 pb-4 text-center text-[0.8125rem] text-muted-foreground">
          {box === "attention" ? "Nobody needs attention right now." : `Nobody in "${title}".`}
        </p>
      )}
      <p className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border px-5 py-2 text-[0.71875rem] text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Dot kind="ok" /> submitted
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Dot kind="miss" /> nothing submitted
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Dot kind="off" /> no ticket / no login yet
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Dot kind="future" /> day not come yet
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Dot kind="rev" /> reviewed (verify / approve / return)
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Dot kind="pending" /> today – nothing yet
        </span>
        <span>· click a row for the details</span>
      </p>

      <FullList open={full} onClose={() => setFull(false)} people={people} r={r} today={today} tab={tab} onOpen={setDetail} />
      <PersonDetail p={detail} r={r} today={today} onClose={() => setDetail(null)} />
    </Card>
  );
}

/** One line per person: name (+ FRT code), FE (FRT), GPs, not filled, week dots, days submitted. */
function CompactTable({ rows, r, today, frt, onOpen, showReasons = false }: { rows: Person[]; r: TicketReport; today: string; frt: boolean; onOpen: (p: Person) => void; showReasons?: boolean }) {
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] text-[0.8125rem]">
        <thead className="text-left text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
          <tr className="border-b border-border">
            <th className="px-5 py-1.5 font-semibold">{frt ? "FRT team" : "Name"}</th>
            {frt && <th className="px-2 py-1.5 font-semibold">FE</th>}
            <th className="px-2 py-1.5 text-right font-semibold">GPs</th>
            <th className="px-2 py-1.5 text-right font-semibold">Not filled</th>
            <th className="px-3 py-1.5 font-semibold">Week</th>
            <th className="px-5 py-1.5 text-right font-semibold" title="Days with a Daily Achievement or a review – of the days they were expected to work (today counts once something is done)">Active days</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const can = workDays(p, r.days, r.today ?? "");
            const why = showReasons ? attention(p, r.days, r.today ?? "") : [];
            return (
              <tr key={personKey(p)} onClick={() => onOpen(p)} className="cursor-pointer border-b border-border last:border-0 hover:bg-accent/40">
                <td className="max-w-[18rem] truncate px-5 py-2">
                  <span className="font-semibold">{frt && !p.account ? (p.frtCodes ?? [p.name]).join(", ") : p.name}</span>
                  {frt && p.account && !!p.frtCodes?.length && <span className="ml-1.5 rounded bg-primary-soft px-1 py-0.5 text-[0.65625rem] font-semibold text-primary">{p.frtCodes.join(", ")}</span>}
                  {!p.account && <span className="ml-1.5 text-[0.6875rem] text-muted-foreground">no login</span>}
                  {why.map((w) => (
                    <span key={w} className="ml-1.5 rounded bg-critical-soft px-1 py-0.5 text-[0.65625rem] font-semibold text-critical-text">
                      {w}
                    </span>
                  ))}
                </td>
                {frt && <td className="max-w-[12rem] truncate px-2 py-2 text-muted-foreground">{(p.fes ?? []).join(", ") || "—"}</td>}
                <td className="px-2 py-2 text-right font-semibold">{p.gps}</td>
                <td className="whitespace-nowrap px-2 py-2 text-right">
                  {p.status?.none ?? 0}
                  {!!p.status?.C && <span className="ml-1 rounded bg-warning-soft px-1 text-[0.65625rem] font-semibold text-warning-text">{p.status.C} revisit</span>}
                  {!!p.status?.D && <span className="ml-1 rounded bg-critical-soft px-1 text-[0.65625rem] font-semibold text-critical-text">{p.status.D} ND</span>}
                </td>
                <td className="px-3 py-2">
                  <WeekDots p={p} days={r.days} today={today} />
                </td>
                <td className="whitespace-nowrap px-5 py-2 text-right">
                  {p.account && p.gps > 0 ? (
                    <span className={cn("font-semibold", can.length && !p.activeDays ? "text-critical-text" : p.activeDays === can.length && can.length ? "text-good-text" : "")}>
                      {p.activeDays} / {can.length}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Everybody of the role, in a large dialog: search, FE / login filter, sort, pages. */
function FullList({ open, onClose, people, r, today, tab, onOpen }: { open: boolean; onClose: () => void; people: Person[]; r: TicketReport; today: string; tab: Tab; onOpen: (p: Person) => void }) {
  const [text, setText] = useState("");
  const [fe, setFe] = useState(ALL);
  const [login, setLogin] = useState<"all" | "with" | "without">("all");
  const [sort, setSort] = useState<"name" | "attention" | "notfilled" | "gps">("name");
  const [page, setPage] = useState(1);
  const frt = tab === "FRT";
  const fes = useMemo(() => [...new Set(people.flatMap((p) => p.fes ?? []))].sort(), [people]);
  const q = text.trim().toLowerCase();
  const rows = useMemo(() => {
    const out = people.filter(
      (p) =>
        (!q || `${p.name} ${(p.frtCodes ?? []).join(" ")} ${(p.fes ?? []).join(" ")} ${p.circles.join(" ")}`.toLowerCase().includes(q)) &&
        (fe === ALL || (p.fes ?? []).includes(fe)) &&
        (login === "all" || (login === "with") === p.account),
    );
    return out.sort((a, b) =>
      sort === "attention"
        ? attention(b, r.days, r.today ?? "").length - attention(a, r.days, r.today ?? "").length || a.name.localeCompare(b.name)
        : sort === "notfilled"
          ? (b.status?.none ?? 0) - (a.status?.none ?? 0) || a.name.localeCompare(b.name)
          : sort === "gps"
            ? b.gps - a.gps || a.name.localeCompare(b.name)
            : (frt ? ((a.fes ?? [])[0] ?? "~").localeCompare((b.fes ?? [])[0] ?? "~") : 0) || a.name.localeCompare(b.name),
    );
  }, [people, q, fe, login, sort, frt, r.days, r.today]);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageNo = Math.min(page, pages);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="top-[5vh] max-h-[90dvh] max-w-5xl p-0">
        <div className="space-y-3 border-b border-border p-5">
          <DialogTitle className="text-lg font-bold">
            All {ROLE_LABEL[tab]} <span className="font-normal text-muted-foreground">({rows.length})</span>
          </DialogTitle>
          <DialogDescription className="sr-only">Every {tab} of this week&apos;s tickets</DialogDescription>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-full sm:w-56">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input value={text} onChange={(e) => (setText(e.target.value), setPage(1))} placeholder={frt ? "Search FRT, code or FE" : "Search name or circle"} className="h-9 pl-8 text-[0.8125rem]" aria-label="Search" />
            </div>
            {frt && (
              <Select ariaLabel="FE" value={fe} onValueChange={(v) => (setFe(v), setPage(1))} options={[{ value: ALL, label: "All FEs" }, ...fes.map((x) => ({ value: x, label: x }))]} className="w-48" />
            )}
            <Select
              ariaLabel="Login"
              value={login}
              onValueChange={(v) => (setLogin(v as typeof login), setPage(1))}
              options={[
                { value: "all", label: "Login: all" },
                { value: "with", label: "With login" },
                { value: "without", label: "Without login" },
              ]}
              className="w-40"
            />
            <Select
              ariaLabel="Sort"
              value={sort}
              onValueChange={(v) => (setSort(v as typeof sort), setPage(1))}
              options={[
                { value: "name", label: frt ? "Sort: FE, name" : "Sort: name" },
                { value: "attention", label: "Sort: needs attention" },
                { value: "notfilled", label: "Sort: most not filled" },
                { value: "gps", label: "Sort: most GPs" },
              ]}
              className="ml-auto w-52"
            />
          </div>
        </div>
        <CompactTable rows={rows.slice((pageNo - 1) * PAGE_SIZE, pageNo * PAGE_SIZE)} r={r} today={today} frt={frt} onOpen={onOpen} showReasons />
        {!rows.length && <p className="p-6 text-center text-[0.8125rem] text-muted-foreground">Nobody matches.</p>}
        {pages > 1 && (
          <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-2.5 text-[0.8125rem]">
            {(pageNo - 1) * PAGE_SIZE + 1}–{Math.min(pageNo * PAGE_SIZE, rows.length)} of {rows.length}
            <Button size="sm" variant="outline" onClick={() => setPage(pageNo - 1)} disabled={pageNo <= 1}>
              ‹ Prev
            </Button>
            <Button size="sm" variant="outline" onClick={() => setPage(pageNo + 1)} disabled={pageNo >= pages}>
              Next ›
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** One person's week: login, last submission, status, returns, day by day. */
function PersonDetail({ p, r, today, onClose }: { p: Person | null; r: TicketReport; today: string; onClose: () => void }) {
  const why = p ? attention(p, r.days, r.today ?? "") : [];
  return (
    <Dialog open={!!p} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md p-0">
        {p && (
          <div className="space-y-3 p-5 text-[0.8125rem]">
            <div>
              <DialogTitle className="text-lg font-bold">
                {p.role === "FRT" && !p.account ? (p.frtCodes ?? [p.name]).join(", ") : p.name}
                {p.role === "FRT" && p.account && !!p.frtCodes?.length && <span className="ml-2 rounded bg-primary-soft px-1.5 py-0.5 text-[0.75rem] font-semibold text-primary">{p.frtCodes.join(", ")}</span>}
              </DialogTitle>
              <DialogDescription className="mt-0.5 text-muted-foreground">
                {ROLE_LABEL[p.role].replace(/s$/, "")} · {p.circles.join(", ") || "—"}
                {p.role === "FRT" ? ` · FE ${(p.fes ?? []).join(", ") || "none"}` : ""}
              </DialogDescription>
            </div>
            {!!why.length && (
              <p className="flex flex-wrap gap-1.5">
                {why.map((w) => (
                  <span key={w} className="rounded bg-critical-soft px-1.5 py-0.5 text-[0.71875rem] font-semibold text-critical-text">
                    {w}
                  </span>
                ))}
              </p>
            )}
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5">
              <dt className="text-muted-foreground">Login</dt>
              <dd>{p.account ? `yes${p.loginSince ? `, since ${fmtDate(p.loginSince)}` : ""}` : "no login"}</dd>
              <dt className="text-muted-foreground">Last signed in</dt>
              <dd>{p.account ? (ago(p.lastLogin, today) ?? "never") : "—"}</dd>
              <dt className="text-muted-foreground">Last active</dt>
              <dd>{p.account ? (ago(p.lastActive, today) ?? "never") : "—"}</dd>
              <dt className="text-muted-foreground">Last submitted</dt>
              <dd>{p.account ? (ago(p.lastSubmission, today) ?? "never") : "—"}</dd>
              <dt className="text-muted-foreground">Tickets · GPs</dt>
              <dd>
                {p.tickets} · {p.gps} ({p.done} done)
              </dd>
              <dt className="text-muted-foreground">Returned</dt>
              <dd>{p.returns ?? 0}×</dd>
            </dl>
            <div className="space-y-1.5">
              <StatusBar s={p.status} wide />
              <p className="flex flex-wrap gap-x-3 gap-y-1 text-[0.75rem]">
                {STATUS.filter((x) => p.status?.[x.key]).map((x) => (
                  <span key={x.key} className="inline-flex items-center gap-1">
                    <span className="size-2 rounded-full" style={{ background: x.color }} aria-hidden /> {x.label} <b>{p.status?.[x.key]}</b>
                  </span>
                ))}
              </p>
            </div>
            <ul className="space-y-1 rounded-lg border border-border p-2.5">
              {r.days.map((d) => {
                const c = p.days[d.date];
                return (
                  <li key={d.date} className="flex items-center gap-2">
                    <WeekDots p={p} days={[d]} today={today} />
                    <span className="w-24">
                      {dayHead(d.date).wd} {fmtDate(d.date)}
                    </span>
                    <span className={cn("text-muted-foreground", !c && !d.future && p.account && p.gps > 0 && (!p.ticketSince || d.date >= p.ticketSince) && (!p.loginSince || d.date >= p.loginSince) && "text-critical-text")}>
                      {c
                        ? dayText(c)
                        : d.future
                          ? "not come yet"
                          : p.ticketSince && d.date < p.ticketSince
                            ? "no ticket yet"
                            : !p.account || (p.loginSince && d.date < p.loginSince)
                              ? "no login"
                              : p.gps > 0
                                ? "nothing submitted"
                                : "no GPs"}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

type DotKind = "ok" | "rev" | "miss" | "pending" | "off" | "future";

function Dot({ kind, title, today = false }: { kind: DotKind; title?: string; today?: boolean }) {
  return (
    <span
      title={title}
      aria-label={title}
      role={title ? "img" : undefined}
      className={cn(
        "inline-block size-3 shrink-0 rounded-full",
        kind === "ok" && "bg-[var(--good)]",
        kind === "rev" && "bg-sky-500",
        kind === "pending" && "bg-[var(--warning)]",
        kind === "miss" && "bg-[var(--critical)]",
        kind === "off" && "bg-muted-foreground/25",
        kind === "future" && "border border-muted-foreground/40 bg-transparent",
        today && "ring-2 ring-primary/40 ring-offset-1",
      )}
    />
  );
}

/** The week in 7 dots (Saturday → Friday); hover = what happened that day. */
function WeekDots({ p, days, today }: { p: Person; days: Day[]; today: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      {days.map((d) => {
        const c = p.days[d.date];
        const label = `${dayHead(d.date).wd} ${fmtDate(d.date)}`;
        let kind: DotKind;
        let title: string;
        if (c) {
          kind = c.subs ? "ok" : "rev";
          title = `${label}: ${dayText(c)}`;
        } else if (d.future) {
          kind = "future";
          title = `${label}: not come yet`;
        } else if (p.ticketSince && d.date < p.ticketSince) {
          kind = "off";
          title = `${label}: no ticket yet (generated ${fmtDate(p.ticketSince)})`;
        } else if (!p.account || (p.loginSince && d.date < p.loginSince)) {
          kind = "off";
          title = `${label}: no login${p.loginSince ? ` yet (created ${fmtDate(p.loginSince)})` : " – the FE / AM fills its GPs"}`;
        } else if (p.gps === 0) {
          kind = "off";
          title = `${label}: no GPs`;
        } else if (d.date === today) {
          kind = "pending";
          title = `${label}: nothing yet today`;
        } else {
          kind = "miss";
          title = `${label}: nothing submitted`;
        }
        return <Dot key={d.date} kind={kind} title={title} today={d.date === today} />;
      })}
    </span>
  );
}

type PendingItem = NonNullable<TicketReport["pending"]>["items"][number];
const BUCKET_TONE: Record<string, string> = {
  not_filled: "var(--muted-foreground)",
  field: "var(--warning)",
  fe_verify: "var(--series-3)",
  am: "var(--series-1)",
  sme: "var(--series-7)",
  coh: "var(--series-2)",
  nd: "var(--critical)",
  closed: "var(--good)",
};

/** Where the work of the week waits now: one box per step (count, overdue), a click lists those GPs with whom / since when. */
function PendingWith({ r }: { r: TicketReport }) {
  const pd = r.pending!;
  const firstOpen = pd.buckets.find((b) => b.key !== "closed" && b.key !== "not_filled" && b.count)?.key ?? "not_filled";
  const [pick, setPick] = useState<string>(firstOpen);
  const [full, setFull] = useState(false);
  const rows = useMemo(() => pd.items.filter((it) => it.bucket === pick), [pd.items, pick]);
  const bucket = pd.buckets.find((b) => b.key === pick);
  const late = pd.buckets.reduce((n, b) => n + (b.key === "closed" ? 0 : b.overdue), 0);
  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-end gap-2 border-b border-border px-5 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold text-subheading">Pending with</h2>
          <p className="text-[0.8125rem] text-muted-foreground">
            Where each GP of this week waits now, with whom and since when.{" "}
            {late ? <span className="font-semibold text-critical-text">{late} waiting more than {pd.overdueDays} days.</span> : <span className="text-good-text">Nothing waiting more than {pd.overdueDays} days.</span>}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2 px-5 py-3 sm:grid-cols-4 xl:grid-cols-8">
        {pd.buckets.map((b) => (
          <button
            key={b.key}
            type="button"
            onClick={() => setPick(b.key)}
            aria-pressed={pick === b.key}
            className={cn("rounded-lg border px-2.5 py-2 text-left transition-colors hover:bg-accent/40", pick === b.key ? "border-primary bg-primary-soft/40" : "border-border", !b.count && "opacity-60")}
            style={{ borderTop: `3px solid ${BUCKET_TONE[b.key]}` }}
          >
            <span className="block truncate text-[0.6875rem] font-semibold text-muted-foreground">{b.label}</span>
            <span className="text-lg font-bold">{formatCount(b.count)}</span>
            {b.key !== "closed" && b.overdue > 0 && <span className="ml-1 text-[0.6875rem] font-semibold text-critical-text">⏳ {b.overdue}</span>}
          </button>
        ))}
      </div>
      <div className="flex items-center justify-between gap-2 px-5 pb-1">
        <h3 className="text-[0.8125rem] font-semibold text-subheading">
          {bucket?.label} <span className="font-normal text-muted-foreground">({rows.length}) – longest waiting first</span>
        </h3>
        {rows.length > LIST_MAX && (
          <Button size="sm" variant="outline" onClick={() => setFull(true)}>
            View all {rows.length} →
          </Button>
        )}
      </div>
      <PendingTable rows={rows.slice(0, LIST_MAX)} overdueDays={pd.overdueDays} />
      {!rows.length && <p className="px-5 pb-4 pt-2 text-center text-[0.8125rem] text-muted-foreground">No GP here.</p>}
      <Dialog open={full} onOpenChange={setFull}>
        <DialogContent className="top-[5vh] max-h-[90dvh] max-w-5xl p-0">
          <div className="border-b border-border p-5">
            <DialogTitle className="text-lg font-bold">
              {bucket?.label} <span className="font-normal text-muted-foreground">({rows.length})</span>
            </DialogTitle>
            <DialogDescription className="text-[0.8125rem] text-muted-foreground">Longest waiting first.</DialogDescription>
          </div>
          <PendingTable rows={rows} overdueDays={pd.overdueDays} />
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function PendingTable({ rows, overdueDays }: { rows: PendingItem[]; overdueDays: number }) {
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[44rem] text-[0.8125rem]">
        <thead className="text-left text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
          <tr className="border-b border-border">
            <th className="px-5 py-1.5 font-semibold">GP</th>
            <th className="px-2 py-1.5 font-semibold">Ticket</th>
            <th className="px-2 py-1.5 font-semibold">Stage</th>
            <th className="px-2 py-1.5 font-semibold">With</th>
            <th className="px-5 py-1.5 text-right font-semibold">Waiting</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((it, i) => (
            <tr key={`${it.ticketId}:${it.gpCode}:${i}`} className="border-b border-border last:border-0">
              <td className="max-w-[16rem] truncate px-5 py-2">
                <b>{it.gpCode ?? "—"}</b> <span className="text-muted-foreground">{it.gpName ?? ""}{it.block ? ` · ${it.block}` : ""}</span>
              </td>
              <td className="px-2 py-2">
                <Link href={`/dashboard/tickets/admin?ticket=${it.ticketId}`} className="font-medium text-primary hover:underline">
                  {it.ticket ?? `#${it.ticketId}`}
                </Link>
              </td>
              <td className="max-w-[14rem] truncate px-2 py-2 text-muted-foreground">{it.stage}</td>
              <td className="max-w-[14rem] truncate px-2 py-2">
                {it.who} {it.whoRole !== "—" && <span className="rounded bg-muted px-1 py-0.5 text-[0.65625rem] font-semibold text-muted-foreground">{it.whoRole}</span>}
              </td>
              <td className={cn("whitespace-nowrap px-5 py-2 text-right font-semibold", it.bucket !== "closed" && it.days > overdueDays ? "text-critical-text" : "")}>
                {it.bucket === "closed" ? "—" : it.days === 0 ? "today" : `${it.days} day${it.days === 1 ? "" : "s"}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const pctTone = (pct: number) => (pct >= 70 ? "var(--good)" : pct >= 30 ? "var(--warning)" : "var(--critical)");

/** Achievement % per Area Manager (highest first): GPs, achieved, a bar, and where the GPs not achieved wait now. */
function AmAchievement({ r }: { r: TicketReport }) {
  const rows = r.amAchievement ?? [];
  const [open, setOpen] = useState<(typeof rows)[number] | null>(null);
  const label = Object.fromEntries((r.pending?.buckets ?? []).map((b) => [b.key, b.label]));
  const total = rows.reduce((a, x) => ({ gps: a.gps + x.gps, done: a.done + x.done }), { gps: 0, done: 0 });
  const totalPct = total.gps ? Math.round((total.done * 1000) / total.gps) / 10 : 0;
  const gpRows = useMemo(() => {
    if (!open?.ticketIds || !r.pending) return [];
    const ids = new Set(open.ticketIds);
    return r.pending.items.filter((it) => ids.has(it.ticketId));
  }, [open, r.pending]);
  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-base font-bold text-subheading">Achievement by Area Manager</h2>
        <p className="text-[0.8125rem] text-muted-foreground">
          GPs of this week&apos;s tickets that are achieved, per AM – top achiever first. &quot;Waiting at&quot; shows where the rest are now. Click a row for the GPs.
        </p>
      </div>
      <div className="max-h-[26rem] overflow-auto">
        <table className="w-full min-w-[46rem] text-[0.8125rem]">
          <thead className="sticky top-0 z-10 bg-muted text-left text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-5 py-2 font-semibold">Area Manager</th>
              <th className="px-2 py-2 text-right font-semibold">GPs</th>
              <th className="px-2 py-2 text-right font-semibold">Achieved</th>
              <th className="w-[30%] px-3 py-2 font-semibold">Achievement</th>
              <th className="px-5 py-2 font-semibold">Waiting at</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={`${a.name}:${a.circles.join()}`} onClick={() => setOpen(a)} className="cursor-pointer border-t border-border hover:bg-muted/40">
                <td className="px-5 py-2">
                  <span className="font-semibold">{a.name}</span>
                  {!a.account && <span className="ml-1.5 rounded bg-muted px-1 py-0.5 text-[0.65625rem] font-semibold text-muted-foreground">no login</span>}
                  <span className="block text-[0.71875rem] text-muted-foreground">
                    {a.tickets} ticket{a.tickets === 1 ? "" : "s"}
                    {a.circles.length ? ` · ${a.circles.join(", ")}` : ""}
                  </span>
                </td>
                <td className="px-2 py-2 text-right">{formatCount(a.gps)}</td>
                <td className="px-2 py-2 text-right font-semibold">{formatCount(a.done)}</td>
                <td className="px-3 py-2">
                  {a.gps ? (
                    <div className="flex items-center gap-2">
                      <div className="relative h-2.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${a.pct}% achieved`}>
                        <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${Math.max(a.pct, a.pct > 0 ? 2 : 0)}%`, background: pctTone(a.pct) }} />
                      </div>
                      <span className="w-12 text-right font-bold" style={{ color: pctTone(a.pct) }}>
                        {a.pct}%
                      </span>
                    </div>
                  ) : (
                    <span className="text-muted-foreground">no GPs</span>
                  )}
                </td>
                <td className="px-5 py-2 text-[0.75rem] text-muted-foreground">
                  {Object.entries(a.waiting)
                    .sort((x, y) => (y[1] ?? 0) - (x[1] ?? 0))
                    .map(([k, n]) => `${label[k] ?? k} ${n}`)
                    .join(" · ") || "—"}
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={5} className="px-5 py-6 text-center text-muted-foreground">
                  No Area Manager on this week&apos;s tickets.
                </td>
              </tr>
            )}
          </tbody>
          {rows.length > 1 && (
            <tfoot>
              <tr className="border-t-2 border-border bg-muted/40 font-semibold">
                <td className="px-5 py-2">Total</td>
                <td className="px-2 py-2 text-right">{formatCount(total.gps)}</td>
                <td className="px-2 py-2 text-right">{formatCount(total.done)}</td>
                <td className="px-3 py-2" style={{ color: pctTone(totalPct) }}>
                  {totalPct}%
                </td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="top-[5vh] max-h-[90dvh] max-w-5xl p-0">
          <div className="border-b border-border p-5">
            <DialogTitle className="text-lg font-bold">
              {open?.name} <span className="font-normal text-muted-foreground">· {open?.done} of {open?.gps} GPs achieved ({open?.pct}%)</span>
            </DialogTitle>
            <DialogDescription className="text-[0.8125rem] text-muted-foreground">Every GP of their tickets this week – where it waits now, longest waiting first.</DialogDescription>
          </div>
          <div className="max-h-[70dvh] overflow-auto">
            <PendingTable rows={gpRows} overdueDays={r.pending?.overdueDays ?? 2} />
            {!gpRows.length && <p className="p-6 text-center text-[0.8125rem] text-muted-foreground">No GP.</p>}
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/** GP returns: who sent which GP back, to whom, why (the remark) – and who gets returns most often. */
function Returns({ r }: { r: TicketReport }) {
  const ret = r.returns!;
  const [who, setWho] = useState<string | null>(null);
  const rows = who ? ret.items.filter((x) => `${x.toRole}:${x.to}` === who) : ret.items;
  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-base font-bold text-subheading">Returns – who, to whom, why</h2>
        <p className="text-[0.8125rem] text-muted-foreground">
          GPs of this week&apos;s tickets sent back for correction (FE → FRT, AM → FE, SME / COH → AM), with the reason given. Click a name to see only theirs.
        </p>
      </div>
      {ret.top.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 px-5 pt-3">
          <span className="text-[0.75rem] font-semibold text-muted-foreground">Returned most:</span>
          {ret.top.slice(0, 8).map((t) => {
            const k = `${t.role}:${t.name}`;
            return (
              <button
                key={k}
                type="button"
                aria-pressed={who === k}
                onClick={() => setWho(who === k ? null : k)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-[0.75rem] transition-colors",
                  who === k ? "border-critical bg-critical-soft text-critical-text" : "border-border hover:bg-muted",
                )}
              >
                {t.name} <span className="text-muted-foreground">{t.role}</span> <b>{t.count}×</b>
              </button>
            );
          })}
          {who && (
            <button type="button" onClick={() => setWho(null)} className="text-[0.75rem] font-medium text-primary hover:underline">
              Show all
            </button>
          )}
        </div>
      )}
      <div className="mt-2 max-h-[26rem] overflow-auto">
        <table className="w-full min-w-[50rem] text-[0.8125rem]">
          <thead className="sticky top-0 z-10 bg-muted text-left text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
            <tr>
              {["When", "GP", "Ticket", "Returned by", "Returned to", "Reason"].map((h) => (
                <th key={h} className="px-4 py-2 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((x, i) => (
              <tr key={`${x.ticketId}:${x.gpCode}:${x.at}:${i}`} className="border-t border-border">
                <td className="whitespace-nowrap px-4 py-2">{fmtTime(x.at)}</td>
                <td className="max-w-[14rem] truncate px-4 py-2">
                  <b>{x.gpCode ?? "—"}</b> <span className="text-muted-foreground">{x.gpName ?? ""}{x.block ? ` · ${x.block}` : ""}</span>
                </td>
                <td className="whitespace-nowrap px-4 py-2">
                  <Link href={`/dashboard/tickets/admin?ticket=${x.ticketId}`} className="font-medium text-primary hover:underline">
                    {x.ticket ?? `#${x.ticketId}`}
                  </Link>
                </td>
                <td className="whitespace-nowrap px-4 py-2">
                  {x.by ?? "—"} {x.byRole && <span className="rounded bg-muted px-1 py-0.5 text-[0.65625rem] font-semibold text-muted-foreground">{x.byRole}</span>}
                </td>
                <td className="whitespace-nowrap px-4 py-2">
                  {x.to} <span className="rounded bg-critical-soft px-1 py-0.5 text-[0.65625rem] font-semibold text-critical-text">{x.toRole}</span>
                  {x.frtCode && x.frtCode !== x.to && <span className="ml-1 text-[0.71875rem] text-muted-foreground">{x.frtCode}</span>}
                </td>
                <td className="max-w-[20rem] px-4 py-2 text-muted-foreground" title={x.remark ?? ""}>
                  <span className="line-clamp-2">{x.remark || "—"}</span>
                </td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-muted-foreground">
                  No GP returned on this week&apos;s tickets.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Completed({ r }: { r: TicketReport }) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-base font-bold text-subheading">Completed this week</h2>
        <p className="text-[0.8125rem] text-muted-foreground">
          GPs that became Done – in a daily submission or with the letter submitted by the COH –, AMC conversions and approved Non-Doable cases – who and when
          {r.completedTotal && r.completedTotal > r.completed.length ? ` (latest ${r.completed.length} of ${r.completedTotal}; all in the Excel)` : ""}.
        </p>
      </div>
      <div className="max-h-[26rem] overflow-auto">
        <table className="w-full min-w-[44rem] text-sm">
          <thead className="sticky top-0 z-10 bg-muted text-left text-[0.75rem] uppercase tracking-wide text-muted-foreground">
            <tr>
              {["When", "What", "GP", "Ticket", "By"].map((h) => (
                <th key={h} className="px-4 py-2.5 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {r.completed.map((c, i) => (
              <tr key={`${c.ticketId}:${c.gpCode}:${c.what}:${i}`} className="border-t border-border">
                <td className="whitespace-nowrap px-4 py-2 text-[0.8125rem]">{fmtTime(c.at)}</td>
                <td className="px-4 py-2">
                  <span className={cn("rounded-full px-2 py-0.5 text-[0.71875rem] font-semibold", WHAT[c.what].cls)}>{WHAT[c.what].label}</span>
                </td>
                <td className="px-4 py-2">
                  <span className="font-semibold">{c.gpCode ?? "—"}</span>{" "}
                  <span className="text-[0.8125rem] text-muted-foreground">
                    {c.gpName ?? ""}
                    {c.block ? ` · ${c.block}` : ""}
                  </span>
                </td>
                <td className="px-4 py-2">
                  <Link href={`/dashboard/tickets/admin?ticket=${c.ticketId}`} className="font-medium text-primary hover:underline">
                    {c.ticket ?? `#${c.ticketId}`}
                  </Link>
                </td>
                <td className="px-4 py-2 text-[0.8125rem]">
                  {c.by ?? "—"} {c.byRole && <span className="rounded bg-muted px-1.5 py-0.5 text-[0.6875rem] font-semibold text-muted-foreground">{c.byRole}</span>}
                </td>
              </tr>
            ))}
            {!r.completed.length && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                  Nothing completed in this week yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** SME / COH: they review the GPs (no Daily Achievement) – kept in one small card. */
function Reviewers({ r }: { r: TicketReport }) {
  const [open, setOpen] = useState<"SME" | "COH" | null>(null);
  const sel = open ? r.roles.find((y) => y.role === open) : undefined;
  const steps = sel?.steps ?? [];
  return (
    <Card className="p-5">
      <h2 className="text-base font-bold text-subheading">Review – SME / COH</h2>
      <p className="mb-3 text-[0.8125rem] text-muted-foreground">
        They review the GPs instead of a Daily Achievement: the tickets they are on and the review steps done this week. Click a box to see which GPs.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {(["SME", "COH"] as const).map((role) => {
          const x = r.roles.find((y) => y.role === role);
          return (
            <button
              key={role}
              type="button"
              onClick={() => setOpen(role)}
              className="flex items-center gap-3 rounded-lg border border-border px-4 py-3 text-left transition-colors hover:border-primary/50 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <ShieldCheck className="size-5 shrink-0 text-primary" aria-hidden />
              <div className="min-w-0 flex-1 text-sm">
                <p className="font-semibold">{role}</p>
                <p className="text-[0.8125rem] text-muted-foreground">
                  {formatCount(x?.people ?? 0)} {x?.people === 1 ? "person" : "people"} · {formatCount(x?.tickets ?? 0)} ticket{x?.tickets === 1 ? "" : "s"} ·{" "}
                  <b className="text-foreground">{formatCount(x?.reviewed ?? 0)}</b> review step{x?.reviewed === 1 ? "" : "s"} this week
                </p>
              </div>
              <span className="shrink-0 text-[0.75rem] font-medium text-primary">View</span>
            </button>
          );
        })}
      </div>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="top-[5vh] max-h-[90dvh] max-w-4xl p-0">
          <div className="border-b border-border px-5 py-3">
            <DialogTitle className="text-lg font-bold">{open} – review steps this week</DialogTitle>
            <DialogDescription className="text-[0.8125rem] text-muted-foreground">
              {formatCount(steps.length)} step{steps.length === 1 ? "" : "s"} on this week&apos;s tickets · latest first
            </DialogDescription>
          </div>
          <div className="max-h-[70dvh] overflow-auto">
            <table className="w-full min-w-[44rem] text-sm">
              <thead className="sticky top-0 z-10 bg-muted text-left text-[0.75rem] uppercase tracking-wide text-muted-foreground">
                <tr>
                  {["When", "What", "GP", "Ticket", "By", "Remark"].map((h) => (
                    <th key={h} className="px-4 py-2.5 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {steps.map((s, i) => (
                  <tr key={`${s.ticketId}:${s.gpCode}:${s.at}:${i}`} className="border-t border-border">
                    <td className="whitespace-nowrap px-4 py-2 text-[0.8125rem]">{fmtTime(s.at)}</td>
                    <td className="whitespace-nowrap px-4 py-2">
                      <span
                        className={cn(
                          "rounded-full px-2 py-0.5 text-[0.71875rem] font-semibold",
                          s.action.startsWith("Returned") ? "bg-critical-soft text-critical-text" : "bg-good-soft text-good-text",
                        )}
                      >
                        {s.action}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <span className="font-semibold">{s.gpCode ?? "—"}</span>{" "}
                      <span className="text-[0.8125rem] text-muted-foreground">
                        {s.gpName ?? ""}
                        {s.block ? ` · ${s.block}` : ""}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2">
                      <Link href={`/dashboard/tickets/admin?ticket=${s.ticketId}`} className="font-medium text-primary hover:underline">
                        {s.ticket ?? `#${s.ticketId}`}
                      </Link>
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-[0.8125rem]">{s.by ?? "—"}</td>
                    <td className="max-w-[16rem] truncate px-4 py-2 text-[0.8125rem] text-muted-foreground" title={s.remark ?? ""}>
                      {s.remark || "—"}
                    </td>
                  </tr>
                ))}
                {!steps.length && (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-muted-foreground">
                      No review steps this week yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function Trend({ r }: { r: TicketReport }) {
  const max = Math.max(1, ...r.trend.map((t) => t.gps));
  return (
    <Card className="p-5">
      <h2 className="text-base font-bold text-subheading">Week by week</h2>
      <p className="mb-3 text-[0.8125rem] text-muted-foreground">Tickets generated, their GPs and Done GPs in the last ticket weeks.</p>
      <ul className="space-y-2.5">
        {r.trend.map((t) => (
          <li key={t.week} className={cn("grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-3 text-[0.8125rem]", t.week === r.week?.code && "font-semibold")}>
            <span>{t.week}</span>
            <div className="min-w-0">
              <div className="relative h-4 overflow-hidden rounded bg-muted" title={`${t.gps} GPs · ${t.done} done`}>
                <div className="absolute inset-y-0 left-0 rounded bg-[var(--series-1)]/35" style={{ width: `${(t.gps / max) * 100}%` }} />
                <div className="absolute inset-y-0 left-0 rounded bg-[var(--good)]" style={{ width: `${(t.done / max) * 100}%` }} />
              </div>
              <span className="text-[0.75rem] text-muted-foreground">
                {t.tickets} ticket{t.tickets === 1 ? "" : "s"} · {formatCount(t.gps)} GPs · {formatCount(t.done)} done
              </span>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
