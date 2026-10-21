"use client";

import { ChevronDown, ChevronsLeft, ChevronsRight, LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Logo } from "@/components/brand/logo";
import { Tooltip } from "@/components/ui/overlays";
import { useFilters } from "@/hooks/use-filters";
import { useSession } from "@/hooks/use-session";
import { IS_LIVE } from "@/lib/api";
import { AMC_PATH, AMC_VIEWS, amcViewFrom } from "@/lib/amc-views";
import { BLOCK_PATH, BLOCK_VIEWS, blockViewFrom } from "@/lib/block-views";
import { FIELD_PATH, FIELD_VIEWS, fieldViewFrom } from "@/lib/field-views";
import { CIRCLE_PATH, CIRCLE_VIEWS, circleViewFrom } from "@/lib/circle-views";
import { GP_PATH, GP_VIEWS, gpViewFrom } from "@/lib/gp-views";
import { OVERVIEW_PATH, OVERVIEW_VIEWS, overviewViewFrom } from "@/lib/overview-views";
import { REVIEW_PAGES, REVIEW_PATH, reviewPageFrom } from "@/lib/review-pages";
import { cn } from "@/lib/utils/cn";
import { NAV, isActive } from "./nav-config";

/** A page whose sections are listed under its sidebar item (selected via one URL parameter). */
interface SubMenu {
  param: string;
  label: string;
  items: readonly { id: string; title: string; short: string }[];
  current: string;
  open: boolean;
}

export function SidebarContent({
  collapsed = false,
  onToggle,
  onNavigate,
}: {
  collapsed?: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { hrefTo } = useFilters();
  // Sub-menus: one link per section of a page (Circle Overview / Circle / Block / GP Insights ?view=, Management Review ?page=), keeping
  // week / filters. A list opens only while its page is open; the chevron can fold it away there.
  const subMenus: Record<string, SubMenu> = {
    [OVERVIEW_PATH]: { param: "view", label: "Circle Overview views", items: OVERVIEW_VIEWS, current: overviewViewFrom(searchParams.get("view")), open: pathname === OVERVIEW_PATH },
    [CIRCLE_PATH]: { param: "view", label: "Circle Insights views", items: CIRCLE_VIEWS, current: circleViewFrom(searchParams.get("view")), open: pathname.startsWith(CIRCLE_PATH) },
    [BLOCK_PATH]: { param: "view", label: "Block Insights views", items: BLOCK_VIEWS, current: blockViewFrom(searchParams.get("view")), open: pathname.startsWith(BLOCK_PATH) },
    [GP_PATH]: { param: "view", label: "GP Insights views", items: GP_VIEWS, current: gpViewFrom(searchParams.get("view")), open: pathname.startsWith(GP_PATH) },
    [AMC_PATH]: { param: "view", label: "AMC conversion views", items: AMC_VIEWS, current: amcViewFrom(searchParams.get("view")), open: pathname.startsWith(AMC_PATH) },
    [FIELD_PATH]: { param: "view", label: "Field Team & Escalation views", items: FIELD_VIEWS, current: fieldViewFrom(searchParams.get("view")), open: pathname.startsWith(FIELD_PATH) },
    [REVIEW_PATH]: { param: "page", label: "Management Review pages", items: REVIEW_PAGES, current: reviewPageFrom(searchParams.get("page")), open: pathname.startsWith(REVIEW_PATH) },
  };
  const subHref = (path: string, param: string, id: string) => {
    const base = hrefTo(path);
    return `${base}${base.includes("?") ? "&" : "?"}${param}=${id}`;
  };
  const [folded, setFolded] = useState<Record<string, boolean>>({});
  const { session, isAdmin, logout } = useSession();
  const initials = session?.name.split(" ").map((p) => p[0]).join("").slice(0, 2) ?? "··";

  return (
    <div className="flex h-full flex-col">
      <div className={cn("flex h-16 shrink-0 items-center border-b border-sidebar-border", collapsed ? "justify-center px-2" : "px-5")}>
        <Link href={hrefTo("/dashboard")} onClick={onNavigate} aria-label="Pratap – Circle Overview" className="rounded">
          {collapsed ? <Logo variant="mark" width={30} eager /> : <Logo variant="wordmark" width={112} eager />}
        </Link>
      </div>

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-4">
        {NAV.map((group) => {
          const items = group.items.filter((i) => !i.adminOnly || isAdmin);
          if (!items.length) return null;
          return (
            <div key={group.label} className="mb-5">
              {!collapsed ? (
                <p className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-subtle-foreground">{group.label}</p>
              ) : (
                <div className="mx-auto mb-2 h-px w-6 bg-sidebar-border" aria-hidden />
              )}
              <ul className="space-y-0.5">
                {items.map((item) => {
                  const active = isActive(pathname, item.href);
                  const menu = subMenus[item.href];
                  const showSub = !!menu && menu.open && !folded[item.href];
                  const link = (
                    <Link
                      href={hrefTo(item.href)}
                      onClick={() => {
                        if (menu) setFolded((f) => ({ ...f, [item.href]: false }));
                        onNavigate?.();
                      }}
                      aria-current={active ? "page" : undefined}
                      aria-label={collapsed ? item.label : undefined}
                      className={cn(
                        "relative flex h-9 items-center gap-3 rounded-md text-sm transition-colors",
                        collapsed ? "justify-center" : "px-3",
                        menu?.open && !collapsed && "pr-8",
                        active ? "bg-primary-soft font-medium text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      )}
                    >
                      {active && <span className="brand-gradient absolute inset-y-1.5 left-0 w-[3px] rounded-full" aria-hidden />}
                      <item.icon className={cn("size-[18px] shrink-0", active && "text-primary")} />
                      {!collapsed && <span className="line-clamp-2 leading-tight">{item.label}</span>}
                    </Link>
                  );
                  return (
                    <li key={item.href}>
                      {collapsed ? (
                        <Tooltip content={item.label} side="right">
                          {link}
                        </Tooltip>
                      ) : menu?.open ? (
                        <div className="relative">
                          {link}
                          <button
                            type="button"
                            onClick={() => setFolded((f) => ({ ...f, [item.href]: !f[item.href] }))}
                            aria-expanded={showSub}
                            aria-label={showSub ? `Hide ${menu.label}` : `Show ${menu.label}`}
                            className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                          >
                            <ChevronDown className={cn("size-4 transition-transform", !showSub && "-rotate-90")} />
                          </button>
                        </div>
                      ) : (
                        link
                      )}
                      {menu && showSub && (
                        <ul aria-label={menu.label} className={cn("mt-0.5 space-y-0.5", !collapsed && "ml-[21px] border-l border-sidebar-border pl-2")}>
                          {menu.items.map((pg, i) => {
                            const on = menu.current === pg.id;
                            const sub = (
                              <Link
                                href={subHref(item.href, menu.param, pg.id)}
                                onClick={onNavigate}
                                aria-current={on ? "page" : undefined}
                                aria-label={collapsed ? `${i + 1}: ${pg.title}` : undefined}
                                className={cn(
                                  "flex items-center gap-2 rounded-md text-[13px] transition-colors",
                                  // full names: a long one wraps to a second line instead of being cut off
                                  collapsed ? "mx-auto h-7 w-7 justify-center" : "min-h-8 px-2 py-1.5 leading-snug",
                                  on ? "bg-primary-soft font-medium text-primary" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                                )}
                              >
                                <span className={cn("flex size-5 shrink-0 items-center justify-center rounded text-[11px] font-semibold", on ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>{i + 1}</span>
                                {!collapsed && <span className="min-w-0 break-words">{pg.short}</span>}
                              </Link>
                            );
                            return (
                              <li key={pg.id}>
                                {collapsed ? (
                                  <Tooltip content={`${i + 1} · ${pg.title}`} side="right">
                                    {sub}
                                  </Tooltip>
                                ) : (
                                  sub
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className="shrink-0 border-t border-sidebar-border p-3">
        <div className={cn("flex items-center gap-3 rounded-md", collapsed ? "flex-col" : "px-2 py-1.5")}>
          <div className="brand-gradient flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white" aria-hidden>
            {initials}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{session?.name ?? "—"}</p>
              <p className="truncate text-xs capitalize text-muted-foreground">{session ? (IS_LIVE ? session.role : `${session.role} · demo`) : ""}</p>
            </div>
          )}
          <Tooltip content="Log out" side={collapsed ? "right" : "top"}>
            <button type="button" onClick={logout} aria-label="Log out" className="rounded-md p-2 text-muted-foreground hover:bg-accent hover:text-foreground">
              <LogOut className="size-4" />
            </button>
          </Tooltip>
        </div>
        {onToggle && (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "mt-2 flex h-8 w-full items-center gap-2 rounded-md text-xs text-muted-foreground hover:bg-accent hover:text-foreground",
              collapsed ? "justify-center" : "px-3",
            )}
          >
            {collapsed ? <ChevronsRight className="size-4" /> : <ChevronsLeft className="size-4" />}
            {!collapsed && "Collapse"}
          </button>
        )}
      </div>
    </div>
  );
}
