"use client";

import { Bell, CalendarDays, Menu, Monitor, Moon, RefreshCw, Search, Sun, LogOut } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { DemoBadge } from "@/components/feedback/badges";
import { useMeta, useRefresh } from "@/components/providers/data-provider";
import { useTheme, type ThemePreference } from "@/components/providers/theme-provider";
import { Button } from "@/components/ui/button";
import {
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
import { api } from "@/lib/api";
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
        <kbd className="ml-auto hidden rounded border border-border bg-muted px-1.5 py-0.5 font-sans text-[10px] font-medium text-muted-foreground sm:inline">Ctrl K</kbd>
      </button>

      <div className="ml-auto flex items-center gap-1 sm:gap-1.5">
        <HeaderWeekSelect />
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
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <CalendarDays className="size-4" aria-hidden /> Week
      </span>
      <Select
        ariaLabel="Reporting week"
        className="h-9 w-[180px] font-medium"
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

function Notifications() {
  const { period, hrefTo } = useFilters();
  const { data } = useApiQuery(period ? `notifications:${period.weekId}` : null, () => api.getNotifications(period!.weekId));
  const [seen, setSeen] = useState(false);
  const count = data?.filter((n) => n.severity !== "info").length ?? 0;
  const tone = { info: "bg-primary", warning: "bg-warning", critical: "bg-critical" } as const;
  return (
    <Popover onOpenChange={(o) => o && setSeen(true)}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Notifications${count && !seen ? `, ${count} need attention` : ""}`} className="relative">
          <Bell />
          {count > 0 && !seen && <span className="absolute right-2 top-2 size-2 rounded-full bg-critical ring-2 ring-background" aria-hidden />}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <p className="text-sm font-semibold">Notifications</p>
          <span className="text-[11px] font-medium uppercase tracking-wide text-warning-text">Demo</span>
        </div>
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
  const initials = session?.name.split(" ").map((p) => p[0]).join("").slice(0, 2) ?? "··";
  return (
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
          <p className="mt-1 text-[11px] capitalize text-subtle-foreground">{session?.role} · demo session</p>
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
        <DropdownMenuItem onSelect={logout}>
          <LogOut /> Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
