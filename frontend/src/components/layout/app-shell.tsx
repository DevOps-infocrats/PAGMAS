"use client";

import { ShieldAlert, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { CommandPalette } from "@/components/navigation/command-palette";
import { SidebarContent } from "@/components/navigation/sidebar";
import { useMeta, useMetaError } from "@/components/providers/data-provider";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { useSession } from "@/components/providers/session-provider";
import { Card } from "@/components/ui/primitives";
import { pageOfPath, usePageAccess } from "@/lib/auth/access";
import { Dialog, DialogDescription, DialogTitle, SheetContent } from "@/components/ui/overlays";
import { cn } from "@/lib/utils/cn";
import { IS_LIVE } from "@/lib/api";
import { formatDate } from "@/lib/utils/format";
import { useIsLoadingData } from "@/lib/loading-store";
import { Header, MobileWeekBar } from "./header";

const COLLAPSE_KEY = "pratap-sidebar-collapsed";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const metaError = useMetaError();

  useEffect(() => {
    try {
      // Restore the per-browser sidebar preference after hydration.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage unavailable */
    }
  }, []);

  const toggle = () =>
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      } catch {
        /* ignore */
      }
      return !c;
    });

  return (
    <div className="flex min-h-dvh">
      <DataLoadingBar />
      <a href="#main" className="sr-only z-50 rounded bg-card px-3 py-2 focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        Skip to content
      </a>
      <aside
        className={cn(
          "sticky top-0 z-40 hidden h-dvh shrink-0 border-r border-sidebar-border bg-sidebar transition-[width] duration-200 lg:block",
          collapsed ? "w-[4.25rem]" : "w-[15.5rem]",
        )}
      >
        <SidebarContent collapsed={collapsed} onToggle={toggle} />
      </aside>

      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent>
          <DialogTitle className="sr-only">Navigation</DialogTitle>
          <DialogDescription className="sr-only">Main navigation menu</DialogDescription>
          <SidebarContent onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Dialog>

      <div className="flex min-w-0 flex-1 flex-col">
        <Header onOpenMobileNav={() => setMobileOpen(true)} onOpenSearch={() => setSearchOpen(true)} />
        <MobileWeekBar />
        <main id="main" className="mx-auto w-full max-w-[97.5rem] flex-1 px-4 py-5 sm:px-6 lg:px-8 lg:py-6">
          <AccessDeniedNotice />
          {metaError ? <ErrorState error={metaError} /> : <PageGuard>{children}</PageGuard>}
        </main>
        <footer className="border-t border-border px-4 py-3.5 text-center text-xs text-subtle-foreground lg:px-8">
          <FooterNote />
        </footer>
      </div>

      <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} />
    </div>
  );
}

/**
 * Roles & Access: a page the user's role does not show on this device opens the role's start page instead (the server
 * refuses that page's data anyway – backend app.security.roles). Admin pages / settings keep their own AdminGuard.
 */
function PageGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { session, loading } = useSession();
  const access = usePageAccess();
  const key = pageOfPath(pathname);
  const allowed = access.can(key);
  const home = access.home;
  const elsewhere = pageOfPath(home.split("?")[0]) !== key;
  useEffect(() => {
    if (!loading && session && !allowed && elsewhere) router.replace(`${home}${home.includes("?") ? "&" : "?"}denied=role`);
  }, [loading, session, allowed, elsewhere, home, router]);
  if (key === null) return <>{children}</>;
  if (loading || !session) return null; // never a flash of a page the role does not show
  if (allowed) return <>{children}</>;
  return elsewhere ? null : (
    <Card>
      <EmptyState icon={ShieldAlert} title="No page for your role" description={`Your role${access.roleName ? ` (${access.roleName})` : ""} shows no dashboard page on this device. Please ask an administrator.`} />
    </Card>
  );
}

function AccessDeniedNotice() {
  const param = useSearchParams().get("denied");
  const [dismissed, setDismissed] = useState(false);
  if ((param !== "1" && param !== "role") || dismissed) return null;
  return (
    <div role="alert" className="mb-6 flex items-start gap-3 rounded-lg border border-warning/40 bg-warning-soft px-4 py-3 text-sm text-warning-text">
      <ShieldAlert className="mt-0.5 size-4 shrink-0" />
      <p className="flex-1">
        {param === "role"
          ? "That page is not part of your role – you were taken to your start page."
          : "That page is for admin accounts only. You were redirected to the Circle Overview."}
      </p>
      <button type="button" aria-label="Dismiss" onClick={() => setDismissed(true)} className="rounded p-0.5 hover:bg-black/5">
        <X className="size-4" />
      </button>
    </div>
  );
}

function FooterNote() {
  const meta = useMeta();
  if (!IS_LIVE) return <>Demo mode · all figures are generated demo data</>;
  return (
    <>
      Pratap network analytics · {meta?.datasetFileName ?? "—"}
      {meta?.dataAsOf ? ` · data as of ${formatDate(meta.dataAsOf)}` : ""}
    </>
  );
}

/** Thin animated bar at the very top while any dashboard data is loading. */
function DataLoadingBar() {
  const loading = useIsLoadingData();
  return loading ? <div className="data-progress" role="progressbar" aria-label="Loading data" /> : null;
}
