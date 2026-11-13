"use client";

import { AlertTriangle, Bell, CalendarDays, Info, KeyRound, Menu, Monitor, Moon, RefreshCw, Search, Sun, LogOut } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ChangePasswordForm, PASSWORD_RULE } from "@/components/account/change-password-form";
import { DemoBadge } from "@/components/feedback/badges";
import { useMeta, useRefresh } from "@/components/providers/data-provider";
import { useTheme, type ThemePreference } from "@/components/providers/theme-provider";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  Tooltip,
} from "@/components/ui/overlays";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { useSession } from "@/hooks/use-session";
import { IS_LIVE, api, ticketApi } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatShortDate } from "@/lib/utils/format";

export function Header({ onOpenMobileNav, onOpenSearch }: { onOpenMobileNav: () => void; onOpenSearch: () => void }) {
  return (
    <header className="sticky top-0 z-30 flex h-14 shadow-[0_1px_0_0_var(--border)] items-center gap-2 border-b border-border bg-card px-4 sm:gap-3 lg:px-8">
      <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" onClick={onOpenMobileNav}>
        <Menu />
      </Button>

      <button
        type="button"
        onClick={onOpenSearch}
        className="flex h-9 min-w-0 flex-1 items-center gap-2.5 rounded-md border border-border bg-card px-3 text-sm text-subtle-foreground transition-colors hover:border-input sm:max-w-md"
        aria-label="Search circles, blocks and GPs"
      >
        <Search className="size-4 shrink-0" />
        <span className="truncate">Search circles, blocks, GPs…</span>
        <kbd className="ml-auto hidden rounded border border-border bg-muted px-1.5 py-0.5 font-sans text-[0.625rem] font-medium text-muted-foreground sm:inline">Ctrl K</kbd>
      </button>

      <div className="ml-auto flex items-center gap-1 sm:gap-1.5">
        <HeaderWeekSelect />
        <DataStatus />
        <DemoBadge className="mx-1 hidden md:inline-flex" />
        <span className="mx-1 hidden h-6 w-px bg-border md:block" aria-hidden />
        <RefreshButton />
        <Notifications />
        <UserMenu />
      </div>
    </header>
  );
}

function HeaderWeekSelect() {
  const meta = useMeta();
  const { period, setFilters } = useFilters();
  const weeks = [...(meta?.weeks ?? [])].reverse();
  return (
    <div className="hidden items-center gap-2 md:flex">
      <span className="flex items-center gap-1.5 text-xs font-semibold text-foreground/75">
        <CalendarDays className="size-4" aria-hidden /> Week
      </span>
      <Select
        ariaLabel="Reporting week"
        className="h-9 w-[11.25rem]"
        value={period?.weekId}
        placeholder="Loading weeks…"
        disabled={!meta}
        options={weeks.map((w) => ({ value: w.id, label: `${w.label} · ${formatShortDate(w.endDate)}` }))}
        onValueChange={(v) => {
          const idx = weeks.findIndex((w) => w.id === v);
          setFilters({ week: v, compare: weeks[idx + 1]?.id ?? v });
        }}
      />
    </div>
  );
}

/** Data date of the active file (warning once it is older than the backend's limit) and a note when the selected
 * week's availability was recomputed from the daily values. */
function DataStatus() {
  const meta = useMeta();
  const { period } = useFilters();
  if (!meta?.dataAsOf) return null;
  const age = meta.dataAgeDays ?? 0;
  const stale = meta.staleAfterDays != null && age > meta.staleAfterDays;
  const recomputed = meta.recomputedWeeks?.find((w) => w.id === period?.weekId);
  return (
    <div className="hidden items-center gap-1.5 lg:flex">
      <Tooltip side="bottom" content={stale ? `The active data is ${age} days old – upload the latest master data file (Data Operations).` : `Data as of ${formatShortDate(meta.dataAsOf)} · ${meta.datasetFileName ?? ""}`}>
        <span
          tabIndex={0}
          className={cn(
            "inline-flex h-7 items-center gap-1 rounded-full border px-2.5 text-[0.71875rem] font-semibold",
            stale ? "border-warning/40 bg-warning-soft text-warning-text" : "border-border bg-muted/60 text-muted-foreground",
          )}
        >
          {stale && <AlertTriangle className="size-3.5" aria-hidden />}
          Data {formatShortDate(meta.dataAsOf)}
          {stale && ` · ${age}d old`}
        </span>
      </Tooltip>
      {recomputed && (
        <Tooltip side="bottom" content={`${recomputed.note}. The dashboard uses the daily values, so this week can differ from the workbook's weekly column.`}>
          <span tabIndex={0} className="inline-flex h-7 items-center gap-1 rounded-full border border-primary/25 bg-primary-soft px-2.5 text-[0.71875rem] font-semibold text-primary">
            <Info className="size-3.5" aria-hidden /> Recomputed
          </span>
        </Tooltip>
      )}
    </div>
  );
}

function RefreshButton() {
  const { refresh } = useRefresh();
  const [spinning, setSpinning] = useState(false);
  return (
    <Tooltip content="Reload the dashboard data">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Reload data"
        onClick={() => {
          setSpinning(true);
          refresh();
          setTimeout(() => setSpinning(false), 600);
        }}
      >
        <RefreshCw className={cn(spinning && "animate-spin")} />
      </Button>
    </Tooltip>
  );
}

/** Ticket notifications are re-checked every minute (and on Refresh). */
const TICKET_POLL_MS = 60_000;

function Notifications() {
  const { period, hrefTo } = useFilters();
  const { data } = useApiQuery(period ? `notifications:${period.weekId}` : null, () => api.getNotifications(period!.weekId));
  const [poll, setPoll] = useState(0);
  useEffect(() => {
    if (!IS_LIVE) return;
    const id = setInterval(() => setPoll((n) => n + 1), TICKET_POLL_MS);
    return () => clearInterval(id);
  }, []);
  const tickets = useApiQuery(IS_LIVE ? `ticket-notifications:${poll}` : null, () => ticketApi.getNotifications());
  const [seen, setSeen] = useState(false);
  const [readUpTo, setReadUpTo] = useState(0);
  const count = data?.filter((n) => n.severity !== "info").length ?? 0;
  const ticketItems = tickets.data?.items ?? tickets.staleData?.items ?? [];
  const unreadTickets = ticketItems.filter((n) => !n.read && n.id > readUpTo).length;
  const tone = { info: "bg-primary", warning: "bg-warning", critical: "bg-critical" } as const;
  const onOpen = (o: boolean) => {
    if (!o) return;
    setSeen(true);
    if (unreadTickets > 0) {
      setReadUpTo(Math.max(...ticketItems.map((n) => n.id)));
      ticketApi.markNotificationsRead().catch(() => undefined); // best effort: the dot is cleared locally either way
    }
  };
  const attention = (seen ? 0 : count) + unreadTickets;
  return (
    <Popover onOpenChange={onOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Notifications${attention ? `, ${attention} need attention` : ""}`} className="relative">
          <Bell />
          {attention > 0 && <span className="absolute right-2 top-2 size-2 rounded-full bg-critical ring-2 ring-background" aria-hidden />}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <p className="text-sm font-semibold">Notifications</p>
          <span className="text-[0.6875rem] font-medium uppercase tracking-wide text-warning-text">Demo</span>
        </div>
        {ticketItems.length > 0 && (
          <ul aria-label="Ticket notifications" className="max-h-64 divide-y divide-border overflow-y-auto border-b border-border">
            {ticketItems.slice(0, 8).map((n) => (
              <li key={`t-${n.id}`}>
                <Link href={n.href} className={cn("flex gap-3 px-4 py-3 hover:bg-accent", !n.read && "bg-primary-soft/40")}>
                  <NotificationBody title={n.title} body={n.body} dot={n.kind === "CHANGES_REQUESTED" ? "bg-critical" : n.kind === "SUBMITTED" || n.kind === "NONDOABLE" ? "bg-warning" : "bg-primary"} />
                </Link>
              </li>
            ))}
          </ul>
        )}
        <ul className="max-h-96 divide-y divide-border overflow-y-auto">
          {(data ?? []).map((n) => (
            <li key={n.id}>
              {n.href ? (
                <Link href={hrefTo(n.href)} className="flex gap-3 px-4 py-3 hover:bg-accent">
                  <NotificationBody title={n.title} body={n.body} dot={tone[n.severity]} />
                </Link>
              ) : (
                <div className="flex gap-3 px-4 py-3">
                  <NotificationBody title={n.title} body={n.body} dot={tone[n.severity]} />
                </div>
              )}
            </li>
          ))}
          {!data && <li className="px-4 py-6 text-center text-sm text-muted-foreground">Loading…</li>}
        </ul>
      </PopoverContent>
    </Popover>
  );
}

function NotificationBody({ title, body, dot }: { title: string; body: string; dot: string }) {
  return (
    <>
      <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", dot)} aria-hidden />
      <span className="min-w-0">
        <span className="block text-sm font-medium">{title}</span>
        <span className="block text-xs text-muted-foreground">{body}</span>
      </span>
    </>
  );
}

function UserMenu() {
  const { session, logout } = useSession();
  const { preference, setPreference } = useTheme();
  const [pwOpen, setPwOpen] = useState(false);
  const initials = session?.name.split(" ").map((p) => p[0]).join("").slice(0, 2) ?? "··";
  return (
    <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" aria-label="Open profile menu" className="brand-gradient ml-1 flex size-8 items-center justify-center rounded-full text-xs font-semibold text-white shadow-xs ring-2 ring-transparent transition-shadow hover:ring-primary/25">
          {initials}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-60">
        <div className="px-2.5 py-2">
          <p className="text-sm font-medium">{session?.name ?? "—"}</p>
          <p className="text-xs text-muted-foreground">{session?.email}</p>
          <p className="mt-1 text-[0.6875rem] capitalize text-subtle-foreground">{session?.role} · demo session</p>
          {session?.access && (
            <p className="mt-1 text-[0.6875rem] text-muted-foreground">
              Data access: {session.access.scope === "all" ? "all states" : session.access.areas.join(", ")}
            </p>
          )}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={preference} onValueChange={(v) => setPreference(v as ThemePreference)}>
          <DropdownMenuRadioItem value="light">
            <Sun className="mr-2 size-4 text-muted-foreground" /> Light
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon className="mr-2 size-4 text-muted-foreground" /> Dark
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <Monitor className="mr-2 size-4 text-muted-foreground" /> System
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        {IS_LIVE && (
          <DropdownMenuItem onSelect={() => setPwOpen(true)}>
            <KeyRound /> Change password
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={logout}>
          <LogOut /> Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    {/* Every user (admin or viewer) can change their own password here – e.g. after an admin set a first password. */}
    <Dialog open={pwOpen} onOpenChange={setPwOpen}>
      <DialogContent className="max-w-md">
        <DialogTitle>Change your password</DialogTitle>
        <DialogDescription>{PASSWORD_RULE}</DialogDescription>
        <ChangePasswordForm />
      </DialogContent>
    </Dialog>
    </>
  );
}
