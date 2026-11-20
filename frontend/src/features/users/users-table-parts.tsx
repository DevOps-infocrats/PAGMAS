"use client";

/**
 * User Management list: summary cards, search, Circle / BA / District / role / status filters, sorting, pages and a CSV
 * (Excel) download – all in the browser from the users and the location tree the page already loads. The actions
 * (edit / deactivate / delete) are the page's own handlers; nothing here changes how users are stored.
 */

import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Download, Info, MoreHorizontal, Pencil, Search, Trash2, UserCheck, UserX } from "lucide-react";
import { useMemo, useState } from "react";
import { StatusBadge } from "@/components/feedback/badges";
import { SearchableSelect, type SearchableOption } from "@/components/filters/searchable-select";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger, Select } from "@/components/ui/overlays";
import { Input } from "@/components/ui/primitives";
import type { AppUser, UserLocations } from "@/lib/api";
import { cn } from "@/lib/utils/cn";

const PAGE = 25;
const ALL = "__all";

/* ---------------------------------------------------------------- areas: what each user covers */

interface AreaIndex {
  circleName: Map<string, string>;
  ba: Map<string, { name: string; circle: string; blocks: Set<string> }>;
  district: Map<string, { name: string; circle: string; blocks: Set<string> }>;
  blockDistrict: Map<string, string>;
  blockCircle: Map<string, string>;
  blockBas: Map<string, string[]>;
}

function areaIndex(loc: UserLocations | undefined): AreaIndex {
  const idx: AreaIndex = { circleName: new Map(), ba: new Map(), district: new Map(), blockDistrict: new Map(), blockCircle: new Map(), blockBas: new Map() };
  for (const c of loc?.circles ?? []) {
    idx.circleName.set(c.id, c.name);
    for (const b of c.bas ?? []) {
      idx.ba.set(b.id, { name: b.name, circle: c.id, blocks: new Set(b.blocks) });
      for (const bl of b.blocks) idx.blockBas.set(bl, [...(idx.blockBas.get(bl) ?? []), b.id]);
    }
    for (const d of c.districts) {
      idx.district.set(d.id, { name: d.name, circle: c.id, blocks: new Set(d.blocks.map((x) => x.id)) });
      for (const bl of d.blocks) {
        idx.blockDistrict.set(bl.id, d.id);
        idx.blockCircle.set(bl.id, c.id);
      }
    }
  }
  return idx;
}

/** The areas a viewer covers (an admin / a viewer without an area covers everything – `all`). */
interface Coverage {
  all: boolean;
  circles: Set<string>; // circles covered completely
  bas: Set<string>; // BAs covered completely
  districts: Set<string>; // districts covered completely
  blocks: Set<string>; // single blocks
  touchCircles: Set<string>; // every circle the user has anything in
  others: string[]; // GP areas (labels) – shown, not used for the filters
  circleText: string;
  baText: string;
  districtText: string;
}

function coverage(u: AppUser, idx: AreaIndex): Coverage {
  const cv: Coverage = { all: u.role === "admin" || u.scopes.length === 0, circles: new Set(), bas: new Set(), districts: new Set(), blocks: new Set(), touchCircles: new Set(), others: [], circleText: "", baText: "", districtText: "" };
  for (const s of u.scopes) {
    if (s.level === "circle") cv.circles.add(s.id);
    else if (s.level === "ba") cv.bas.add(s.id);
    else if (s.level === "district") cv.districts.add(s.id);
    else if (s.level === "block") cv.blocks.add(s.id);
    else cv.others.push(s.label ?? s.id);
  }
  for (const c of cv.circles) cv.touchCircles.add(c);
  for (const b of cv.bas) {
    const c = idx.ba.get(b)?.circle;
    if (c) cv.touchCircles.add(c);
  }
  for (const d of cv.districts) {
    const c = idx.district.get(d)?.circle;
    if (c) cv.touchCircles.add(c);
  }
  for (const bl of cv.blocks) {
    const c = idx.blockCircle.get(bl);
    if (c) cv.touchCircles.add(c);
  }
  const names = (ids: Iterable<string>, f: (id: string) => string | undefined) => [...new Set([...ids].map(f).filter((x): x is string => !!x))].sort((a, b) => a.localeCompare(b));
  if (cv.all) {
    cv.circleText = cv.baText = cv.districtText = "";
    return cv;
  }
  cv.circleText = names(cv.touchCircles, (id) => idx.circleName.get(id) ?? id).join(", ");
  // BA: chosen BAs; else the BAs of the chosen districts / blocks; a whole circle = all its BAs
  const bas = new Set(cv.bas);
  for (const d of cv.districts) for (const bl of idx.district.get(d)?.blocks ?? []) for (const b of idx.blockBas.get(bl) ?? []) bas.add(b);
  for (const bl of cv.blocks) for (const b of idx.blockBas.get(bl) ?? []) bas.add(b);
  cv.baText = [cv.circles.size ? "All BAs" : "", names(bas, (id) => idx.ba.get(id)?.name).join(", ")].filter(Boolean).join(" + ");
  // district: chosen districts; else the districts of the chosen BAs / blocks; a whole circle = all its districts
  const dists = new Set(cv.districts);
  for (const bl of [...[...cv.bas].flatMap((b) => [...(idx.ba.get(b)?.blocks ?? [])]), ...cv.blocks]) {
    const d = idx.blockDistrict.get(bl);
    if (d) dists.add(d);
  }
  cv.districtText = [cv.circles.size ? "All districts" : "", names(dists, (id) => idx.district.get(id)?.name).join(", ")].filter(Boolean).join(" + ");
  return cv;
}

/** Does the viewer's area include this circle / BA / district? (users who see everything are not area matches) */
function inCircle(cv: Coverage, circle: string) {
  return !cv.all && cv.touchCircles.has(circle);
}
function inBa(cv: Coverage, ba: string, idx: AreaIndex) {
  if (cv.all) return false;
  const info = idx.ba.get(ba);
  if (!info) return false;
  if (cv.bas.has(ba) || cv.circles.has(info.circle)) return true;
  for (const d of cv.districts) for (const bl of idx.district.get(d)?.blocks ?? []) if (info.blocks.has(bl)) return true;
  for (const bl of cv.blocks) if (info.blocks.has(bl)) return true;
  return false;
}
function inDistrict(cv: Coverage, district: string, idx: AreaIndex) {
  if (cv.all) return false;
  const info = idx.district.get(district);
  if (!info) return false;
  if (cv.districts.has(district) || cv.circles.has(info.circle)) return true;
  for (const b of cv.bas) for (const bl of idx.ba.get(b)?.blocks ?? []) if (info.blocks.has(bl)) return true;
  for (const bl of cv.blocks) if (info.blocks.has(bl)) return true;
  return false;
}

/* ---------------------------------------------------------------- list */

type SortKey = "name" | "circle" | "ba" | "district" | "lastLogin" | "status";
type Card = "all" | "active" | "inactive" | "admin" | "viewer" | "never";

const statusOf = (u: AppUser) => (u.locked ? "Locked" : u.isActive ? "Active" : "Inactive");
const shortDate = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });

function csvCell(v: string) {
  // text stays text in Excel: quote it, double inner quotes, and keep a leading = + - @ from becoming a formula
  const t = /^[=+\-@]/.test(v) ? `'${v}` : v;
  return `"${t.replace(/"/g, '""')}"`;
}

export function UsersTable({
  users,
  locations,
  selfEmail,
  onEdit,
  onToggle,
  onRemove,
}: {
  users: AppUser[];
  locations: UserLocations | undefined;
  selfEmail: string | undefined;
  onEdit: (u: AppUser) => void;
  onToggle: (u: AppUser) => void;
  onRemove: (u: AppUser) => void;
}) {
  const idx = useMemo(() => areaIndex(locations), [locations]);
  const rows = useMemo(() => users.map((u) => ({ u, cv: coverage(u, idx) })), [users, idx]);
  const [text, setText] = useState("");
  const [circle, setCircle] = useState<string | undefined>();
  const [ba, setBa] = useState<string | undefined>();
  const [district, setDistrict] = useState<string | undefined>();
  const [role, setRole] = useState(ALL);
  // the roles of the accounts (Admin first) – Roles & Access
  const roleNames = useMemo(() => [...new Set(users.map(roleLabel))].sort((a, b) => (a === "Admin" ? -1 : b === "Admin" ? 1 : a.localeCompare(b))), [users]);
  const [status, setStatus] = useState(ALL);
  const [card, setCard] = useState<Card>("all");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "name", desc: false });
  const [page, setPage] = useState(1);
  const reset = () => setPage(1);

  const circleOpts: SearchableOption[] = useMemo(() => [...idx.circleName].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label)), [idx]);
  const baOpts: SearchableOption[] = useMemo(
    () => [...idx.ba].filter(([, b]) => !circle || b.circle === circle).map(([value, b]) => ({ value, label: circle ? b.name : `${b.name} (${idx.circleName.get(b.circle) ?? ""})` })).sort((a, b) => a.label.localeCompare(b.label)),
    [idx, circle],
  );
  const distOpts: SearchableOption[] = useMemo(
    () =>
      [...idx.district]
        .filter(([, d]) => (!circle || d.circle === circle) && (!ba || [...d.blocks].some((bl) => idx.ba.get(ba)?.blocks.has(bl))))
        .map(([value, d]) => ({ value, label: circle ? d.name : `${d.name} (${idx.circleName.get(d.circle) ?? ""})` }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [idx, circle, ba],
  );

  const q = text.trim().toLowerCase();
  const shown = rows.filter(({ u, cv }) => {
    if (q && !`${u.name} ${u.email} ${u.frtCode ?? ""}`.toLowerCase().includes(q)) return false;
    if (role !== ALL && roleLabel(u) !== role) return false;
    if (status !== ALL && (status === "Active") !== u.isActive) return false; // a locked user counts by its active / inactive state
    if (circle && !inCircle(cv, circle)) return false;
    if (ba && !inBa(cv, ba, idx)) return false;
    if (district && !inDistrict(cv, district, idx)) return false;
    if (card === "active" && !u.isActive) return false;
    if (card === "inactive" && u.isActive) return false;
    if (card === "admin" && u.role !== "admin") return false;
    if (card === "viewer" && u.role !== "viewer") return false;
    if (card === "never" && u.lastLoginAt) return false;
    return true;
  });
  const key = (r: (typeof rows)[number]): string => {
    const { u, cv } = r;
    if (sort.key === "name") return u.name.toLowerCase();
    if (sort.key === "circle") return cv.all ? "￿" : cv.circleText.toLowerCase(); // "everything" sorts last
    if (sort.key === "ba") return cv.all ? "￿" : cv.baText.toLowerCase() || "￾";
    if (sort.key === "district") return cv.all ? "￿" : cv.districtText.toLowerCase() || "￾";
    if (sort.key === "lastLogin") return u.lastLoginAt ?? "";
    return statusOf(u);
  };
  const sorted = [...shown].sort((a, b) => {
    const r = key(a).localeCompare(key(b)) || a.u.name.localeCompare(b.u.name);
    return sort.desc ? -r : r;
  });
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE));
  const cur = Math.min(page, pages);
  const pageRows = sorted.slice((cur - 1) * PAGE, cur * PAGE);
  const filtered = !!(q || circle || ba || district || role !== ALL || status !== ALL || card !== "all");

  const cards: [Card, string, number, string][] = [
    ["all", "Total users", users.length, "var(--series-1)"],
    ["active", "Active", users.filter((u) => u.isActive).length, "var(--good)"],
    ["inactive", "Inactive", users.filter((u) => !u.isActive).length, "var(--muted-foreground)"],
    ["admin", "Admins", users.filter((u) => u.role === "admin").length, "var(--series-7)"],
    ["viewer", "Other roles", users.filter((u) => u.role === "viewer").length, "var(--series-3)"],
    ["never", "Never signed in", users.filter((u) => !u.lastLoginAt).length, "var(--warning)"],
  ];

  const download = () => {
    const head = ["Name", "Email / login", "Role", "FRT code", "Circle", "BA", "District", "Other areas", "Last sign-in", "Status"];
    const lines = sorted.map(({ u, cv }) =>
      [
        u.name,
        u.loginType === "frt" ? `${u.frtCode ?? ""} (FRT code login)` : u.email,
        roleLabel(u),
        u.frtCode ?? "",
        cv.all ? "All" : cv.circleText,
        cv.all ? "All" : cv.baText,
        cv.all ? "All" : cv.districtText,
        cv.others.join("; "),
        u.lastLoginAt ? shortDate(u.lastLoginAt) : "Never",
        statusOf(u),
      ].map(csvCell).join(","),
    );
    const blob = new Blob(["﻿" + [head.map(csvCell).join(","), ...lines].join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `users-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  const th = (children: React.ReactNode, k?: SortKey, className?: string) => (
    <th key={String(children)} scope="col" className={cn("px-3 py-2", className)} aria-sort={k && sort.key === k ? (sort.desc ? "descending" : "ascending") : undefined}>
      {k ? (
        <button
          type="button"
          onClick={() => {
            setSort((s) => (s.key === k ? { key: k, desc: !s.desc } : { key: k, desc: false }));
            reset();
          }}
          className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-foreground"
        >
          {children}
          {sort.key === k ? sort.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" /> : <ArrowUpDown className="size-3 opacity-40" />}
        </button>
      ) : (
        children
      )}
    </th>
  );

  return (
    <div className="space-y-4">
      {/* summary – a card filters the list */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {cards.map(([k, label, n, tone]) => (
          <button
            key={k}
            type="button"
            onClick={() => {
              setCard((c) => (c === k ? "all" : k));
              reset();
            }}
            className={cn("relative overflow-hidden rounded-lg border bg-card px-3 py-2 text-left transition-shadow hover:shadow-sm", card === k && k !== "all" ? "ring-2" : "border-border")}
            style={card === k && k !== "all" ? { borderColor: tone, boxShadow: `0 0 0 2px color-mix(in srgb, ${tone} 45%, transparent)` } : undefined}
            aria-pressed={card === k}
          >
            <span className="absolute inset-x-0 top-0 h-[0.1875rem]" style={{ background: tone }} aria-hidden />
            <span className="block text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">{label}</span>
            <span className="tabular block text-xl font-bold">{n}</span>
          </button>
        ))}
      </div>

      {/* toolbar */}
      <div className="flex flex-wrap items-end gap-2">
        <label className="relative block">
          <span className="sr-only">Search users</span>
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              reset();
            }}
            placeholder="Search name, e-mail, FRT code…"
            className="h-9 w-64 pl-8"
          />
        </label>
        <SearchableSelect
          className="w-48"
          label="Circle"
          hideLabel
          value={circle}
          onChange={(v) => {
            setCircle(v);
            setBa(undefined);
            setDistrict(undefined);
            reset();
          }}
          options={circleOpts}
          placeholder="Circle"
          allowClear
          clearLabel="All circles"
        />
        <SearchableSelect
          className="w-48"
          label="BA"
          hideLabel
          value={ba}
          onChange={(v) => {
            setBa(v);
            setDistrict(undefined);
            reset();
          }}
          options={baOpts}
          placeholder="BA"
          allowClear
          clearLabel="All BAs"
        />
        <SearchableSelect
          className="w-48"
          label="District"
          hideLabel
          value={district}
          onChange={(v) => {
            setDistrict(v);
            reset();
          }}
          options={distOpts}
          placeholder="District"
          allowClear
          clearLabel="All districts"
        />
        <Select
          ariaLabel="Role"
          value={role}
          onValueChange={(v) => {
            if (v) setRole(v);
            reset();
          }}
          options={[{ value: ALL, label: "All roles" }, ...roleNames.map((n) => ({ value: n, label: n }))]}
          className="w-36"
        />
        <Select
          ariaLabel="Status"
          value={status}
          onValueChange={(v) => {
            if (v) setStatus(v);
            reset();
          }}
          options={[
            { value: ALL, label: "All statuses" },
            { value: "Active", label: "Active" },
            { value: "Inactive", label: "Inactive" },
          ]}
          className="w-36"
        />
        {filtered && (
          <button
            type="button"
            className="h-9 px-1 text-[0.8125rem] font-medium text-primary hover:underline"
            onClick={() => {
              setText("");
              setCircle(undefined);
              setBa(undefined);
              setDistrict(undefined);
              setRole(ALL);
              setStatus(ALL);
              setCard("all");
              reset();
            }}
          >
            Clear filters
          </button>
        )}
        <span className="ml-auto flex items-center gap-3">
          <span className="text-[0.8125rem] text-muted-foreground">
            {sorted.length} of {users.length} users
          </span>
          <Button size="sm" variant="outline" onClick={download} disabled={!sorted.length} title="The users of this list (same search, filters and order) – opens in Excel">
            <Download /> Download Excel
          </Button>
        </span>
      </div>

      {/* table */}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[60rem] text-[0.8125rem]">
          <caption className="sr-only">Dashboard users</caption>
          <thead className="bg-muted text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
            <tr>
              {th("User", "name")}
              {th("Role")}
              {th("Circle", "circle")}
              {th("BA", "ba")}
              {th("District", "district")}
              {th("Last sign-in", "lastLogin")}
              {th("Status", "status")}
              {th("Actions", undefined, "text-right")}
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-muted-foreground">
                  No user matches the search and filters.
                </td>
              </tr>
            )}
            {pageRows.map(({ u, cv }) => {
              const self = u.email === selfEmail;
              const everything = <span className="text-muted-foreground">{u.role === "admin" ? "All" : "All (no area)"}</span>;
              return (
                <tr key={u.id} className={cn("border-t border-border/70 align-top transition-colors hover:bg-muted/40", !u.isActive && "text-muted-foreground")}>
                  <td className="px-3 py-2.5">
                    <span className="flex items-center gap-2.5">
                      <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-full text-[0.75rem] font-bold", u.isActive ? "bg-primary-soft text-primary" : "bg-muted text-muted-foreground")} aria-hidden>
                        {u.name.trim().slice(0, 1).toUpperCase()}
                      </span>
                      <span className="min-w-0">
                        <span className="block font-semibold text-foreground">{u.name}</span>
                        <span className="block truncate text-[0.75rem] text-muted-foreground" title={u.email}>
                          {u.loginType === "frt" ? `Login: FRT code ${u.frtCode ?? ""} (no e-mail)` : u.email}
                        </span>
                      </span>
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={cn("rounded-full px-2 py-0.5 text-[0.71875rem] font-semibold", u.role === "admin" ? "bg-[color-mix(in_srgb,var(--series-7)_14%,transparent)] text-[var(--series-7)]" : "bg-muted text-foreground")}>
                      {roleLabel(u)}
                    </span>
                    {u.frtCode && (
                      <span className="mt-1 block w-fit rounded bg-primary-soft px-1.5 py-0.5 text-[0.65625rem] font-semibold text-primary" title="FRT login – reports the Daily Achievement of the GPs of this FRT code">
                        FRT {u.frtCode}
                      </span>
                    )}
                  </td>
                  <td className="max-w-[12rem] px-3 py-2.5">{cv.all ? everything : <span className="line-clamp-2" title={cv.circleText}>{cv.circleText || "—"}</span>}</td>
                  <td className="max-w-[12rem] px-3 py-2.5">{cv.all ? everything : <span className="line-clamp-2" title={cv.baText}>{cv.baText || "—"}</span>}</td>
                  <td className="max-w-[14rem] px-3 py-2.5">
                    {cv.all ? everything : <span className="line-clamp-2" title={cv.districtText}>{cv.districtText || "—"}</span>}
                    {(cv.blocks.size > 0 || cv.others.length > 0) && (
                      <span className="mt-0.5 block text-[0.6875rem] text-muted-foreground" title={u.scopes.filter((s) => s.level === "block" || s.level === "gp").map((s) => s.label ?? s.id).join("\n")}>
                        {[cv.blocks.size ? `${cv.blocks.size} block${cv.blocks.size === 1 ? "" : "s"}` : "", cv.others.length ? `${cv.others.length} GP${cv.others.length === 1 ? "" : "s"}` : ""].filter(Boolean).join(" · ")}
                      </span>
                    )}
                    {u.scopes.some((s) => !s.valid) && <span className="mt-0.5 block text-[0.6875rem] text-warning-text">Some areas are not in the active data</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-muted-foreground">{u.lastLoginAt ? shortDate(u.lastLoginAt) : <span className="text-muted-foreground/70">Never</span>}</td>
                  <td className="px-3 py-2.5">
                    {u.locked ? <StatusBadge tone="warning">Locked</StatusBadge> : u.isActive ? <StatusBadge tone="good">Active</StatusBadge> : <StatusBadge tone="neutral">Inactive</StatusBadge>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <Button size="sm" variant="ghost" onClick={() => onEdit(u)} aria-label={`Edit ${u.name}`}>
                      <Pencil /> Edit
                    </Button>
                    {!self && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button size="sm" variant="ghost" aria-label={`More actions for ${u.name}`}>
                            <MoreHorizontal />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent>
                          <DropdownMenuItem onSelect={() => onToggle(u)}>
                            {u.isActive ? <UserX className="size-4" /> : <UserCheck className="size-4" />} {u.isActive ? "Deactivate" : "Activate"}
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem onSelect={() => onRemove(u)} className="text-critical-text">
                            <Trash2 className="size-4" /> Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {pages > 1 && (
        <nav aria-label="User pages" className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span className="text-muted-foreground">
            Showing {(cur - 1) * PAGE + 1}–{Math.min(cur * PAGE, sorted.length)} of {sorted.length}
          </span>
          <span className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setPage(cur - 1)} disabled={cur <= 1}>
              <ChevronLeft /> Previous
            </Button>
            <span className="tabular text-muted-foreground">
              Page {cur} of {pages}
            </span>
            <Button variant="outline" size="sm" onClick={() => setPage(cur + 1)} disabled={cur >= pages}>
              Next <ChevronRight />
            </Button>
          </span>
        </nav>
      )}
    </div>
  );
}

/** The role shown for a user: Admin, else their access role (Roles & Access) – no role = the built-in Viewer. */
export const roleLabel = (u: AppUser) => (u.role === "admin" ? "Admin" : (u.roleName ?? "Viewer"));

/** The roles and areas explanation, folded. */
export function RolesHelp() {
  return (
    <details className="group rounded-lg border border-border bg-muted/30 px-3 py-2 text-[0.8125rem]">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-medium text-primary [&::-webkit-details-marker]:hidden">
        <Info className="size-4" aria-hidden /> How roles and areas work
      </summary>
      <p className="mt-2 text-muted-foreground">
        <b>Admin</b> – manages data, users and mail; sees every page and every circle. Every other account has a <b>role</b> (Viewer, AM, FE, FRT or one made in{" "}
        <b>Roles &amp; Access</b>) – the role decides <b>which pages</b> it sees on a laptop and on a phone, the same for every user of the role. The user&apos;s{" "}
        <b>areas</b> decide <b>which data</b>: a user with areas sees only those areas on every page, list and download, and receives the AMC Conversion e-mail for
        them; without an area they see every state but receive no e-mail. An FRT code makes the account an FRT login (Daily Achievement of that FRT code&apos;s GPs).
      </p>
    </details>
  );
}
