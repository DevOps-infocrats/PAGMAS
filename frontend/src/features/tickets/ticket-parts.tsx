"use client";

import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  CircleDot,
  Download,
  Eye,
  FileText,
  Hourglass,
  ListX,
  Loader2,
  MessageSquareWarning,
  RotateCcw,
  Search,
  Timer,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { Card, Input } from "@/components/ui/primitives";
import { ticketApi, type TicketDetail, type TicketPage, type TicketPriority, type TicketStatus, type TicketSummary } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";

/* ---------------------------------------------------------------- labels & badges */

export const STATUS_META: Record<TicketStatus, { label: string; cls: string; icon: LucideIcon }> = {
  OPEN: { label: "Open", cls: "bg-primary-soft text-primary", icon: CircleDot },
  IN_PROGRESS: { label: "In Progress", cls: "bg-warning-soft text-warning-text", icon: Timer },
  PENDING_REVIEW: { label: "Pending Review", cls: "bg-[color-mix(in_oklab,var(--series-7)_16%,transparent)] text-[var(--series-7)]", icon: Hourglass },
  CHANGES_REQUESTED: { label: "Changes Requested", cls: "bg-critical-soft text-critical-text", icon: RotateCcw },
  CLOSED: { label: "Closed", cls: "bg-good-soft text-good-text", icon: CircleCheck },
};

export const PRIORITY_META: Record<TicketPriority, { label: string; cls: string; dot: string }> = {
  LOW: { label: "Low", cls: "bg-na-soft text-muted-foreground", dot: "bg-subtle-foreground" },
  MEDIUM: { label: "Medium", cls: "bg-primary-soft text-primary", dot: "bg-primary" },
  HIGH: { label: "High", cls: "bg-warning-soft text-warning-text", dot: "bg-warning" },
  CRITICAL: { label: "Critical", cls: "bg-critical-soft text-critical-text", dot: "bg-critical" },
};

export const STATUS_OPTIONS = [{ value: "all", label: "All statuses" }, ...Object.entries(STATUS_META).map(([value, m]) => ({ value, label: m.label }))];
export const PRIORITY_OPTIONS = [{ value: "all", label: "All priorities" }, ...Object.entries(PRIORITY_META).map(([value, m]) => ({ value, label: m.label }))];

/** Status is never colour-only: icon + text. */
export function TicketStatusBadge({ status }: { status: TicketStatus }) {
  const m = STATUS_META[status];
  const Icon = m.icon;
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", m.cls)}>
      <Icon className="size-3.5" aria-hidden />
      {m.label}
    </span>
  );
}

export function PriorityBadge({ priority }: { priority: TicketPriority }) {
  const m = PRIORITY_META[priority];
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold", m.cls)}>
      <span className={cn("size-1.5 rounded-full", m.dot)} aria-hidden />
      {m.label}
    </span>
  );
}

/* ---------------------------------------------------------------- formatting */

const localFmt = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
const localDay = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: "Asia/Kolkata" });

/** Ticket times in Indian Standard Time (the dashboard's reporting timezone). */
export function ticketTime(iso: string | null | undefined): string {
  return iso ? `${localFmt.format(new Date(iso))} IST` : "—";
}
export function ticketDay(iso: string | null | undefined): string {
  return iso ? localDay.format(new Date(iso)) : "—";
}
export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const TEXTAREA =
  "w-full rounded-md border border-input bg-card px-3 py-2 text-sm leading-relaxed shadow-xs placeholder:text-subtle-foreground hover:border-subtle-foreground/50 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 disabled:opacity-60 aria-invalid:border-critical";

/* ---------------------------------------------------------------- messages */

export type Notice = { ok: boolean; text: string } | null;

export function NoticeBar({ notice, onClose }: { notice: Notice; onClose?: () => void }) {
  if (!notice) return null;
  return (
    <p
      role={notice.ok ? "status" : "alert"}
      className={cn("flex items-start justify-between gap-3 rounded-md border px-4 py-2.5 text-sm", notice.ok ? "border-good/30 bg-good-soft text-good-text" : "border-critical/30 bg-critical-soft text-critical-text")}
    >
      <span>{notice.text}</span>
      {onClose && (
        <button type="button" onClick={onClose} className="text-xs font-semibold underline-offset-2 hover:underline">
          Dismiss
        </button>
      )}
    </p>
  );
}

/* ---------------------------------------------------------------- filters & list */

export interface ListFilters {
  search: string;
  status: TicketStatus | "all";
  priority: TicketPriority | "all";
  dateFrom: string;
  dateTo: string;
  page: number;
}

export const EMPTY_FILTERS: ListFilters = { search: "", status: "all", priority: "all", dateFrom: "", dateTo: "", page: 1 };

/** Search waits until typing pauses; every filter change starts again on page 1. */
/** `extra`: one more labelled field in the same row (e.g. the Week filter of User Tickets), placed before "Clear". */
export function TicketFilterBar({
  value,
  onChange,
  searchHint,
  withDates,
  extra,
}: {
  value: ListFilters;
  onChange: (v: ListFilters) => void;
  searchHint: string;
  withDates?: boolean;
  extra?: React.ReactNode;
}) {
  const [text, setText] = useState(value.search);
  useEffect(() => {
    if (text.trim() === value.search) return;
    const t = setTimeout(() => onChange({ ...value, search: text.trim(), page: 1 }), 300);
    return () => clearTimeout(t);
  }, [text, value, onChange]);
  const set = (patch: Partial<ListFilters>) => onChange({ ...value, ...patch, page: 1 });
  const active = value.search || value.status !== "all" || value.priority !== "all" || value.dateFrom || value.dateTo;
  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-3 border-b border-border px-4 py-3 sm:grid-cols-2",
        withDates
          ? "xl:grid-cols-[minmax(0,1.6fr)_repeat(2,minmax(0,1fr))_repeat(2,minmax(0,0.9fr))_auto]"
          : extra
            ? "xl:grid-cols-[minmax(0,1.3fr)_repeat(2,minmax(0,0.85fr))_minmax(0,1.5fr)_auto]"
            : "xl:grid-cols-[minmax(0,1.6fr)_repeat(2,minmax(0,1fr))_auto]",
      )}
    >
      <label className="flex min-w-0 flex-col gap-1">
        <span className="text-xs font-semibold text-foreground/75">Search</span>
        <span className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden />
          <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={100} placeholder={searchHint} className="pl-8" />
        </span>
      </label>
      <div className="flex min-w-0 flex-col gap-1">
        <span className="text-xs font-semibold text-foreground/75">Status</span>
        <Select ariaLabel="Filter by status" value={value.status} options={STATUS_OPTIONS} onValueChange={(v) => set({ status: v as ListFilters["status"] })} className="w-full" />
      </div>
      <div className="flex min-w-0 flex-col gap-1">
        <span className="text-xs font-semibold text-foreground/75">Priority</span>
        <Select ariaLabel="Filter by priority" value={value.priority} options={PRIORITY_OPTIONS} onValueChange={(v) => set({ priority: v as ListFilters["priority"] })} className="w-full" />
      </div>
      {withDates && (
        <>
          <label className="flex min-w-0 flex-col gap-1">
            <span className="text-xs font-semibold text-foreground/75">Created from</span>
            <Input type="date" value={value.dateFrom} max={value.dateTo || undefined} onChange={(e) => set({ dateFrom: e.target.value })} />
          </label>
          <label className="flex min-w-0 flex-col gap-1">
            <span className="text-xs font-semibold text-foreground/75">Created to</span>
            <Input type="date" value={value.dateTo} min={value.dateFrom || undefined} onChange={(e) => set({ dateTo: e.target.value })} />
          </label>
        </>
      )}
      {extra}
      <div className="flex items-end">
        <Button
          variant="ghost"
          size="md"
          disabled={!active}
          onClick={() => {
            setText("");
            onChange(EMPTY_FILTERS);
          }}
        >
          Clear
        </Button>
      </div>
    </div>
  );
}

export interface TicketColumn {
  key: string;
  header: string;
  render: (t: TicketSummary) => React.ReactNode;
  className?: string;
}

/** Ticket table with loading, error, empty state and server-side pages. A row opens the ticket. */
export function TicketTable({
  title,
  page,
  error,
  loading,
  onRetry,
  columns,
  onOpen,
  onPage,
  filtered,
  emptyText,
  filters,
  rowAction,
}: {
  title: string;
  page: TicketPage | undefined;
  error?: Error;
  loading: boolean;
  onRetry: () => void;
  columns: TicketColumn[];
  onOpen: (t: TicketSummary) => void;
  onPage: (p: number) => void;
  filtered: boolean;
  emptyText: string;
  filters: React.ReactNode;
  /** an extra action next to View (admin: Delete) */
  rowAction?: (t: TicketSummary) => React.ReactNode;
}) {
  const pages = page ? Math.max(1, Math.ceil(page.total / page.pageSize)) : 1;
  const from = page && page.total ? (page.page - 1) * page.pageSize + 1 : 0;
  const to = page ? Math.min(page.page * page.pageSize, page.total) : 0;
  return (
    <Card className="overflow-hidden p-0">
      {filters}
      {error ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : !page ? (
        <div className="p-4">
          <TableSkeleton rows={6} />
        </div>
      ) : page.total === 0 ? (
        <EmptyState icon={ListX} title={filtered ? "No tickets match the filters" : "No tickets yet"} description={filtered ? "Change or clear the search and filters." : emptyText} />
      ) : (
        <>
          <div className={cn("overflow-x-auto", loading && "opacity-60 transition-opacity")}>
            <table className="w-full min-w-[53.75rem] text-[0.8125rem]">
              <caption className="sr-only">{title}</caption>
              <thead>
                <tr className="border-b border-border bg-muted/60 text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
                  {columns.map((c) => (
                    <th key={c.key} scope="col" className={cn("px-3 py-2", c.className)}>
                      {c.header}
                    </th>
                  ))}
                  <th scope="col" className="px-3 py-2 text-right">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((t) => (
                  <tr
                    key={t.id}
                    tabIndex={0}
                    aria-label={`Open ticket ${t.code}`}
                    onClick={() => onOpen(t)}
                    onKeyDown={(e) => e.key === "Enter" && onOpen(t)}
                    className="cursor-pointer border-b border-border/70 last:border-0 hover:bg-accent/50 focus-visible:bg-accent/50 focus-visible:outline-none"
                  >
                    {columns.map((c) => (
                      <td key={c.key} className={cn("px-3 py-2.5 align-middle", c.className)}>
                        {c.render(t)}
                      </td>
                    ))}
                    <td className="whitespace-nowrap px-3 py-2.5 text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpen(t);
                        }}
                      >
                        <Eye /> View
                      </Button>
                      {rowAction?.(t)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav aria-label="Ticket pages" className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm">
            <span className="text-muted-foreground">
              Showing {formatCount(from)}–{formatCount(to)} of {formatCount(page.total)} tickets
            </span>
            <span className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => onPage(page.page - 1)} disabled={page.page <= 1 || loading}>
                <ChevronLeft /> Previous
              </Button>
              <span className="tabular text-muted-foreground">
                Page {page.page} of {pages}
              </span>
              <Button variant="outline" size="sm" onClick={() => onPage(page.page + 1)} disabled={page.page >= pages || loading}>
                Next <ChevronRight />
              </Button>
            </span>
          </nav>
        </>
      )}
    </Card>
  );
}

export const CODE_COL: TicketColumn = { key: "code", header: "Ticket ID", render: (t) => <span className="whitespace-nowrap font-semibold text-primary">{t.code}</span> };
export const SUBJECT_COL: TicketColumn = { key: "subject", header: "Subject", render: (t) => <span className="line-clamp-2 max-w-[22.5rem] font-medium">{t.subject}</span> };
export const PRIORITY_COL: TicketColumn = { key: "priority", header: "Priority", render: (t) => <PriorityBadge priority={t.priority} /> };
export const CREATED_COL: TicketColumn = { key: "created", header: "Created Date", render: (t) => <span className="whitespace-nowrap text-muted-foreground">{ticketDay(t.createdAt)}</span> };
export const STATUS_COL: TicketColumn = { key: "status", header: "Status", render: (t) => <TicketStatusBadge status={t.status} /> };

/** Query parameters of the list from the filter state. */
export function listQuery(f: ListFilters) {
  return {
    search: f.search || undefined,
    status: f.status === "all" ? undefined : f.status,
    priority: f.priority === "all" ? undefined : f.priority,
    dateFrom: f.dateFrom || undefined,
    dateTo: f.dateTo || undefined,
    page: f.page,
    pageSize: 15,
  };
}

/* ---------------------------------------------------------------- detail */

export function BackToList({ onBack, label }: { onBack: () => void; label: string }) {
  return (
    <Button variant="outline" size="sm" onClick={onBack}>
      <ArrowLeft /> {label}
    </Button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium">{children}</dd>
    </div>
  );
}

/** Ticket header: ID, subject, status, priority and the people / dates; description below. */
export function TicketInfo({ t, showAssignee }: { t: TicketDetail; showAssignee: boolean }) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-col gap-2 border-b border-border px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-primary">{t.code}</p>
          <h2 className="mt-0.5 text-lg font-bold text-subheading">{t.subject}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <PriorityBadge priority={t.priority} />
          <TicketStatusBadge status={t.status} />
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 px-5 py-4 md:grid-cols-3 xl:grid-cols-6">
        <Field label="Ticket ID">{t.code}</Field>
        <Field label="Created by (admin)">{t.createdBy.name}</Field>
        {t.circle && <Field label="Circle / State">{t.circle}</Field>}
        {showAssignee && (
          <Field label="Assigned user">
            <span className="block truncate">{t.assignee.name}</span>
            <span className="block truncate text-xs font-normal text-muted-foreground">{t.assignee.email}</span>
            {!t.assigneeActive && <span className="block text-xs font-normal text-warning-text">Account inactive</span>}
          </Field>
        )}
        <Field label="Created">{ticketTime(t.createdAt)}</Field>
        <Field label="Started">{ticketTime(t.startedAt)}</Field>
        <Field label="Last submitted">{ticketTime(t.submittedAt)}</Field>
        {t.status === "CLOSED" && (
          <Field label="Closed">
            {ticketTime(t.closedAt)}
            {t.closedBy?.name && <span className="block text-xs font-normal text-muted-foreground">by {t.closedBy.name}</span>}
          </Field>
        )}
      </dl>
      <div className="border-t border-border px-5 py-4">
        <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">Description</p>
        <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">{t.description}</p>
      </div>
    </Card>
  );
}

export function FeedbackCallout({ t }: { t: TicketDetail }) {
  if (!t.feedback) return null;
  return (
    <div role="note" className="flex gap-3 rounded-xl border border-critical/30 bg-critical-soft px-4 py-3">
      <MessageSquareWarning className="mt-0.5 size-5 shrink-0 text-critical-text" aria-hidden />
      <div className="min-w-0 text-sm">
        <p className="font-semibold text-critical-text">Changes requested by {t.feedback.by ?? "admin"}</p>
        <p className="mt-0.5 whitespace-pre-wrap text-foreground">{t.feedback.comment}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          On submission {t.feedback.version} · {ticketTime(t.feedback.at)}
        </p>
      </div>
    </div>
  );
}

export function AttachmentList({ items }: { items: TicketDetail["submissions"][number]["attachments"] }) {
  if (!items.length) return <p className="text-xs text-muted-foreground">No files attached.</p>;
  return (
    <ul className="divide-y divide-border rounded-lg border border-border">
      {items.map((a) => (
        <li key={a.id} className="flex flex-wrap items-center gap-3 px-3 py-2">
          <FileText className="size-4 shrink-0 text-primary" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{a.fileName}</span>
            <span className="block text-xs text-muted-foreground">
              {fileSize(a.size)} · {ticketTime(a.uploadedAt)}
            </span>
          </span>
          {a.previewable && (
            <Button asChild size="sm" variant="ghost">
              <a href={ticketApi.attachmentUrl(a.id, true)} target="_blank" rel="noopener noreferrer">
                <Eye /> Preview
              </a>
            </Button>
          )}
          <Button asChild size="sm" variant="outline">
            <a href={ticketApi.attachmentUrl(a.id)} download={a.fileName}>
              <Download /> Download
            </a>
          </Button>
        </li>
      ))}
    </ul>
  );
}

const REVIEW_LABEL = { PENDING: "Waiting for review", ACCEPTED: "Approved", CHANGES_REQUESTED: "Changes requested" } as const;
const REVIEW_CLS = { PENDING: "text-[var(--series-7)]", ACCEPTED: "text-good-text", CHANGES_REQUESTED: "text-critical-text" } as const;

/** Every submission (newest first) with its files and the admin's review. */
export function SubmissionHistory({ t, emptyText }: { t: TicketDetail; emptyText: string }) {
  return (
    <Card className="p-5">
      <h3 className="text-base font-bold text-subheading">Submission history</h3>
      <p className="text-[0.8125rem] text-muted-foreground">Every submission of the work and the review it received.</p>
      {t.submissions.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <ol className="mt-4 space-y-4">
          {t.submissions.map((s, i) => (
            <li key={s.id} className={cn("rounded-lg border border-border p-4", i === 0 && "border-primary/30 bg-primary-soft/30")}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold">
                  Submission {s.version}
                  {i === 0 && <span className="ml-2 rounded bg-primary-soft px-1.5 py-0.5 text-[0.6875rem] font-semibold text-primary">Latest</span>}
                </p>
                <p className="text-xs text-muted-foreground">
                  {s.submittedBy} · {ticketTime(s.submittedAt)}
                </p>
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{s.description}</p>
              <div className="mt-3">
                <AttachmentList items={s.attachments} />
              </div>
              <p className={cn("mt-3 text-xs font-semibold", REVIEW_CLS[s.review])}>
                {REVIEW_LABEL[s.review]}
                {s.reviewedBy && (
                  <span className="font-normal text-muted-foreground">
                    {" "}
                    · {s.reviewedBy}, {ticketTime(s.reviewedAt)}
                  </span>
                )}
              </p>
              {s.reviewComment && <p className="mt-1 whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-[0.8125rem]">{s.reviewComment}</p>}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

const ACTION_LABEL: Record<string, string> = {
  CREATED: "Ticket created",
  STARTED: "Work started",
  SUBMITTED: "Work submitted for review",
  RESUBMITTED: "Revised work submitted",
  CHANGES_REQUESTED: "Changes requested",
  CLOSED: "Ticket closed",
  SHARED: "Shared with CBH / SME",
  PROGRESS: "Daily progress",
  REVIEW: "GP review",
  NONDOABLE: "Non-Doable case",
  TASK: "GP-wise task attached",
};

export function ActivityLog({ t }: { t: TicketDetail }) {
  return (
    <Card className="p-5">
      <h3 className="text-base font-bold text-subheading">Activity</h3>
      <ol className="mt-3 space-y-3 border-l border-border pl-4">
        {t.events.map((e, i) => (
          <li key={i} className="relative">
            <span className="absolute -left-[1.3125rem] top-1 size-2.5 rounded-full border-2 border-card bg-primary" aria-hidden />
            <p className="text-sm font-medium">{ACTION_LABEL[e.action] ?? e.action}</p>
            <p className="text-xs text-muted-foreground">
              {e.actor} · {ticketTime(e.at)}
              {e.to && <> · {STATUS_META[e.to]?.label ?? e.to}</>}
            </p>
            {e.note && <p className="mt-0.5 line-clamp-3 whitespace-pre-wrap text-xs text-muted-foreground">{e.note}</p>}
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** Confirmation for critical actions (close, request changes, submit), optionally with a comment field. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  busy,
  onConfirm,
  comment,
  danger,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  busy: boolean;
  onConfirm: (comment: string) => void;
  /** Comment field: required = must be filled in (minLength characters, default 5; hint = the error text) */
  comment?: { label: string; placeholder: string; required: boolean; minLength?: number; hint?: string };
  /** red confirm button (Delete) */
  danger?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent>{open && <ConfirmForm {...{ title, description, confirmLabel, busy, onConfirm, comment, danger }} onCancel={() => onOpenChange(false)} />}</DialogContent>
    </Dialog>
  );
}

/** The dialog's form – mounted on every opening, so the comment always starts empty. */
function ConfirmForm({
  title,
  description,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
  comment,
  danger,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  busy: boolean;
  onConfirm: (comment: string) => void;
  onCancel: () => void;
  comment?: { label: string; placeholder: string; required: boolean; minLength?: number; hint?: string };
  danger?: boolean;
}) {
  const [text, setText] = useState("");
  const [touched, setTouched] = useState(false);
  const min = comment?.minLength ?? 5;
  const missing = !!comment?.required && text.trim().length < min;
  return (
    <form
      className="space-y-4 p-6"
      onSubmit={(e) => {
        e.preventDefault();
        setTouched(true);
        if (!missing) onConfirm(text.trim());
      }}
    >
      <div>
        <DialogTitle className="text-lg font-bold">{title}</DialogTitle>
        <DialogDescription className="mt-1 text-sm text-muted-foreground">{description}</DialogDescription>
      </div>
      {comment && (
        <label className="block space-y-1">
          <span className="text-[0.8125rem] font-medium">
            {comment.label}
            {comment.required && <span className="text-critical-text"> *</span>}
          </span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={5}
            maxLength={5000}
            placeholder={comment.placeholder}
            aria-invalid={touched && missing}
            className={TEXTAREA}
          />
          {touched && missing && (
            <span className="text-xs text-critical-text">
              {comment.hint ?? "Explain what needs to be corrected"} (at least {min} characters).
            </span>
          )}
        </label>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" disabled={busy} className={danger ? "bg-critical bg-none text-white hover:brightness-95" : undefined}>
          {busy && <Loader2 className="animate-spin" />} {confirmLabel}
        </Button>
      </div>
    </form>
  );
}

/** ?ticket=<id> of the page: the open ticket (detail) or none (list). */
export function ticketIdFrom(v: string | null): number | null {
  const n = v && /^\d{1,9}$/.test(v) ? Number(v) : NaN;
  return Number.isFinite(n) && n > 0 ? n : null;
}
