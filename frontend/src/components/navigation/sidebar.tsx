"use client";

import { ChevronDown, ChevronLeft, LogOut } from "lucide-react";
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
    <div className="sidebar-surface relative flex h-full flex-col text-sidebar-foreground">
      <div className={cn("flex h-14 shrink-0 items-center border-b border-sidebar-border", collapsed ? "justify-center px-2" : "gap-2.5 px-5")}>
        <Link href={hrefTo("/dashboard")} onClick={onNavigate} aria-label="Pratap – Circle Overview" className="flex items-center gap-2.5 rounded">
          {collapsed ? <Logo variant="mark" width={28} eager /> : <Logo variant="wordmark" width={92} eager />}
        </Link>
        {!collapsed && (
          <span className="mt-1 border-l border-sidebar-border pl-2.5 text-[11px] font-semibold uppercase leading-tight tracking-[0.08em] text-sidebar-muted">
            Network
            <br />
            Analytics
          </span>
        )}
      </div>

      {onToggle && (
        <button
          type="button"
          onClick={onToggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="absolute -right-3 top-[17px] z-10 hidden size-6 items-center justify-center rounded-full border border-sidebar-border bg-card text-muted-foreground shadow-sm transition-colors hover:border-primary/40 hover:text-primary lg:flex"
        >
          <ChevronLeft className={cn("size-3.5 transition-transform", collapsed && "rotate-180")} />
        </button>
      )}

      <nav aria-label="Main" className={cn("scroll-thin flex-1 overflow-y-auto py-4", collapsed ? "px-2" : "px-3")}>
        {NAV.map((group, gi) => {
          const items = group.items.filter((i) => !i.adminOnly || isAdmin);
          if (!items.length) return null;
          return (
            <div key={group.label} className={cn(gi > 0 && "mt-5")}>
              {!collapsed ? (
                <p className="mb-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-sidebar-muted">{group.label}</p>
              ) : (
                gi > 0 && <div className="mx-auto mb-3 h-px w-6 bg-sidebar-border" aria-hidden />
              )}
              <ul className="space-y-0.5">
                {items.map((item) => {
                  const active = isActive(pathname, item.href);
                  const menu = subMenus[item.href];
                  const showSub = !!menu && menu.open && !folded[item.href];
                  const text = item.shortLabel ?? item.label;
                  const link = (
                    <Link
                      href={hrefTo(item.href)}
                      onClick={() => {
                        if (menu) setFolded((f) => ({ ...f, [item.href]: false }));
                        onNavigate?.();
                      }}
                      aria-current={active ? "page" : undefined}
                      aria-label={collapsed || item.shortLabel ? item.label : undefined}
                      className={cn(
                        "group relative flex h-9 items-center gap-3 rounded-md text-[13.5px] transition-colors",
                        collapsed ? "justify-center" : "px-2.5",
                        menu?.open && !collapsed && "pr-8",
                        active ? "brand-gradient font-semibold text-white shadow-[0_6px_16px_-6px_rgb(10_143_196/0.75)]" : "font-medium text-sidebar-foreground hover:bg-sidebar-hover hover:text-sidebar-strong",
                      )}
                    >
                      <item.icon className={cn("size-[18px] shrink-0 transition-colors", active ? "text-white" : "text-sidebar-muted group-hover:text-sidebar-strong")} />
                      {!collapsed && <span className="truncate">{text}</span>}
                    </Link>
                  );
                  return (
                    <li key={item.href}>
                      {collapsed || item.shortLabel ? (
                        <Tooltip content={item.label} side="right">
                          {menu?.open && !collapsed ? <SubToggle link={link} menu={menu} open={showSub} onToggle={() => setFolded((f) => ({ ...f, [item.href]: !f[item.href] }))} /> : link}
                        </Tooltip>
                      ) : menu?.open ? (
                        <SubToggle link={link} menu={menu} open={showSub} onToggle={() => setFolded((f) => ({ ...f, [item.href]: !f[item.href] }))} />
                      ) : (
                        link
                      )}
                      {menu && showSub && (
                        <ul aria-label={menu.label} className={cn("mt-0.5 space-y-0.5", collapsed ? "pb-1" : "relative mb-1.5 ml-[21px] border-l border-sidebar-border pl-2.5")}>
                          {menu.items.map((pg, i) => {
                            const on = menu.current === pg.id;
                            const sub = (
                              <Link
                                href={subHref(item.href, menu.param, pg.id)}
                                onClick={onNavigate}
                                aria-current={on ? "page" : undefined}
                                aria-label={collapsed ? `${i + 1}: ${pg.title}` : undefined}
                                className={cn(
                                  "relative flex items-center rounded-md text-[13px] transition-colors",
                                  collapsed ? "mx-auto h-7 w-7 justify-center text-[11px] font-semibold" : "min-h-8 px-2.5 py-1.5 leading-snug",
                                  on
                                    ? collapsed
                                      ? "brand-gradient text-white"
                                      : "bg-sidebar-hover font-semibold text-sidebar-strong"
                                    : collapsed
                                      ? "bg-sidebar-hover text-sidebar-foreground hover:bg-sidebar-active hover:text-sidebar-strong"
                                      : "text-sidebar-muted hover:bg-sidebar-hover hover:text-sidebar-strong",
                                )}
                              >
                                {!collapsed && on && <span className="absolute -left-[11.5px] inset-y-1.5 w-[3px] rounded-full brand-gradient-v" aria-hidden />}
                                {collapsed ? i + 1 : <span className="min-w-0 break-words">{pg.short}</span>}
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

      <div className={cn("shrink-0 border-t border-sidebar-border", collapsed ? "p-2" : "p-3")}>
        <div className={cn("flex items-center gap-3 rounded-lg", collapsed ? "flex-col gap-2 py-1" : "bg-sidebar-hover px-2.5 py-2")}>
          <div className="brand-gradient flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white shadow-xs" aria-hidden>
            {initials}
          </div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-semibold leading-tight text-sidebar-strong">{session?.name ?? "—"}</p>
              <p className="mt-0.5 truncate text-[11.5px] capitalize text-sidebar-muted">{session ? (IS_LIVE ? session.role : `${session.role} · demo`) : ""}</p>
            </div>
          )}
          <Tooltip content="Log out" side={collapsed ? "right" : "top"}>
            <button type="button" onClick={logout} aria-label="Log out" className="rounded-md p-1.5 text-sidebar-muted transition-colors hover:bg-sidebar-active hover:text-[#ff8f8f]">
              <LogOut className="size-4" />
            </button>
          </Tooltip>
        </div>
      </div>
    </div>
  );
}

/** Nav link of an open page with the chevron that folds its view list away. */
function SubToggle({ link, menu, open, onToggle }: { link: React.ReactNode; menu: SubMenu; open: boolean; onToggle: () => void }) {
  return (
    <div className="relative">
      {link}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-label={open ? `Hide ${menu.label}` : `Show ${menu.label}`}
        className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-white/85 hover:bg-white/15 hover:text-white"
      >
        <ChevronDown className={cn("size-4 transition-transform", !open && "-rotate-90")} />
      </button>
    </div>
  );
}
