"use client";

import { Command } from "cmdk";
import { Boxes, CornerDownLeft, Loader2, Map, MapPin, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { useFilters } from "@/hooks/use-filters";
import { useSession } from "@/hooks/use-session";
import { api, type SearchResult } from "@/lib/api";
import { ALL_NAV_ITEMS } from "./nav-config";

const ICONS = { circle: Map, block: Boxes, gp: MapPin } as const;

/** Ctrl/⌘ + K palette: jump to pages, circles, blocks or GPs. */
export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<{ q: string; items: SearchResult[] }>({ q: "", items: [] });
  const { navigate } = useFilters();
  const { isAdmin } = useSession();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  const q = query.trim();
  useEffect(() => {
    if (q.length < 2) return;
    let cancelled = false;
    const t = setTimeout(() => {
      api.search(q).then((items) => !cancelled && setResults({ q, items }));
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [q]);

  const searching = q.length >= 2 && results.q !== q;
  const items = q.length >= 2 && results.q === q ? results.items : [];

  const go = (r: SearchResult) => {
    onOpenChange(false);
    setQuery("");
    // Current week/compare are kept by `navigate`; lower hierarchy levels are reset.
    if (r.type === "circle") navigate("/dashboard/circle-insights", { circle: r.circleId, district: undefined, block: undefined, gp: undefined });
    if (r.type === "block") navigate("/dashboard/block-insights", { circle: r.circleId, district: r.districtId, block: r.blockId, gp: undefined });
    if (r.type === "gp") navigate("/dashboard/gp-insights", { circle: r.circleId, district: r.districtId, block: r.blockId, gp: r.id });
  };

  const pages = ALL_NAV_ITEMS.filter((i) => (!i.adminOnly || isAdmin) && i.label.toLowerCase().includes(q.toLowerCase()));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent hideClose className="max-w-xl overflow-hidden p-0">
        <DialogTitle className="sr-only">Search</DialogTitle>
        <DialogDescription className="sr-only">Search pages, circles, blocks and GPs</DialogDescription>
        <Command shouldFilter={false} loop>
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Search className="size-4 text-subtle-foreground" />
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder="Search circles, blocks, GPs or LGD code…"
              className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-subtle-foreground"
            />
            {searching && <Loader2 className="size-4 animate-spin text-subtle-foreground" />}
          </div>
          <Command.List className="max-h-[60vh] overflow-y-auto p-2">
            {q.length >= 2 && !searching && items.length === 0 && pages.length === 0 && (
              <Command.Empty className="px-3 py-8 text-center text-sm text-muted-foreground">No results for “{q}”.</Command.Empty>
            )}
            {pages.length > 0 && (
              <Command.Group heading="Pages" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-subtle-foreground">
                {pages.map((p) => (
                  <Command.Item
                    key={p.href}
                    value={`page-${p.href}`}
                    onSelect={() => {
                      onOpenChange(false);
                      setQuery("");
                      navigate(p.href);
                    }}
                    className="flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 text-sm data-[selected=true]:bg-accent"
                  >
                    <p.icon className="size-4 text-muted-foreground" />
                    {p.label}
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {items.length > 0 && (
              <Command.Group heading="Network" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-subtle-foreground">
                {items.map((r) => {
                  const Icon = ICONS[r.type];
                  return (
                    <Command.Item
                      key={`${r.type}-${r.id}`}
                      value={`${r.type}-${r.id}`}
                      onSelect={() => go(r)}
                      className="flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 text-sm data-[selected=true]:bg-accent"
                    >
                      <Icon className="size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0">
                        <span className="block truncate">{r.label}</span>
                        <span className="block truncate text-xs text-muted-foreground">{r.sublabel}</span>
                      </span>
                    </Command.Item>
                  );
                })}
              </Command.Group>
            )}
          </Command.List>
          <div className="flex items-center justify-between border-t border-border px-4 py-2 text-xs text-subtle-foreground">
            <span>Demo data search</span>
            <span className="flex items-center gap-1">
              <CornerDownLeft className="size-3" /> to open
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
