"use client";

import { Copy, KeyRound, Laptop, Loader2, Plus, Save, ShieldCheck, Smartphone, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ErrorState, TableSkeleton } from "@/components/feedback/states";
import { AdminGuard } from "@/components/layout/admin-guard";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/controls";
import { Select } from "@/components/ui/overlays";
import { Card, Input, Label } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { IS_LIVE, adminApi, type AccessRole, type PageAccess, type PageKey, type RolesResponse } from "@/lib/api";
import { cn } from "@/lib/utils/cn";

/**
 * Roles & Access (admin): a role decides WHICH pages its users see – on a laptop and on a phone – and the page each
 * opens after sign-in. The same for every user of the role; WHICH data a user sees is their own areas (User
 * Management). The server enforces the pages (backend app.security.roles).
 */
export function RolesView() {
  return (
    <AdminGuard>
      <RolesContent />
    </AdminGuard>
  );
}

type Draft = { name: string; description: string; pages: Record<PageKey, PageAccess>; laptopHome: PageKey | ""; phoneHome: PageKey | "" };
type Pick = { mode: "edit"; id: number } | { mode: "new"; from?: AccessRole } | null;

const emptyPages = (keys: PageKey[]) => Object.fromEntries(keys.map((k) => [k, { laptop: false, phone: false }])) as Record<PageKey, PageAccess>;

function RolesContent() {
  const [tick, setTick] = useState(0);
  const q = useApiQuery(IS_LIVE ? `roles:${tick}` : null, () => adminApi.listRoles());
  const [pick, setPick] = useState<Pick>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const data = q.data;
  const roles = data?.roles ?? [];
  // the role shown: the one picked, else the first role
  const current: Pick = pick ?? (roles.length ? { mode: "edit", id: roles[0].id } : null);
  const role = current?.mode === "edit" ? roles.find((r) => r.id === current.id) : undefined;

  return (
    <>
      <PageHeader
        title="Roles & Access"
        description="A role decides which pages its users see – on a laptop and on a phone – and the page they open first. Which data a user sees (State / Circle / BA / District / Block / GP) is set per user in User Management."
        actions={
          <Button onClick={() => (setMsg(null), setPick({ mode: "new" }))} disabled={!data}>
            <Plus /> New role
          </Button>
        }
      />
      {!IS_LIVE && <Card className="p-5 text-sm text-muted-foreground">Roles are managed with the backend connected.</Card>}
      {q.error && <ErrorState error={q.error} />}
      {IS_LIVE && !data && !q.error && <TableSkeleton rows={6} />}
      {msg && (
        <p role="status" className={cn("mb-4 rounded-lg border px-4 py-2.5 text-sm", msg.ok ? "border-success/40 bg-success-soft text-success-text" : "border-critical/40 bg-critical-soft text-critical-text")}>
          {msg.text}
        </p>
      )}
      {data && (
        <div className="grid gap-5 lg:grid-cols-[19rem_minmax(0,1fr)]">
          <RoleList data={data} current={current} onPick={(p) => (setMsg(null), setPick(p))} />
          {current && (
            <RoleEditor
              key={current.mode === "edit" ? `e${current.id}:${role?.updatedAt ?? ""}` : `n${current.from?.id ?? ""}`}
              data={data}
              role={role}
              from={current.mode === "new" ? current.from : undefined}
              onSaved={(r, text) => {
                setMsg({ ok: true, text });
                setPick(r ? { mode: "edit", id: r.id } : null);
                setTick((n) => n + 1);
              }}
              onCopy={(r) => (setMsg(null), setPick({ mode: "new", from: r }))}
              onError={(text) => setMsg({ ok: false, text })}
            />
          )}
        </div>
      )}
    </>
  );
}

function RoleList({ data, current, onPick }: { data: RolesResponse; current: Pick; onPick: (p: Pick) => void }) {
  const count = (r: AccessRole) => (Object.values(r.pages) as PageAccess[]).filter((p) => p.laptop || p.phone).length;
  return (
    <Card className="h-fit overflow-hidden p-0">
      <div className="border-b border-border px-4 py-3 text-[0.8125rem] font-semibold text-subheading">Roles ({data.roles.length + 1})</div>
      <ul className="divide-y divide-border">
        <li className="flex items-center gap-3 px-4 py-3">
          <ShieldCheck className="size-4 shrink-0 text-primary" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">Admin</p>
            <p className="text-[0.75rem] text-muted-foreground">Every page, always · {data.admins} account{data.admins === 1 ? "" : "s"}</p>
          </div>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[0.6875rem] font-semibold text-muted-foreground">fixed</span>
        </li>
        {data.roles.map((r) => {
          const on = current?.mode === "edit" && current.id === r.id;
          return (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => onPick({ mode: "edit", id: r.id })}
                className={cn("flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/40", on && "bg-primary-soft")}
                aria-current={on ? "true" : undefined}
              >
                <KeyRound className={cn("size-4 shrink-0", on ? "text-primary" : "text-muted-foreground")} aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold">{r.name}</p>
                  <p className="text-[0.75rem] text-muted-foreground">
                    {count(r)} page{count(r) === 1 ? "" : "s"} · {r.users} user{r.users === 1 ? "" : "s"}
                  </p>
                </div>
                {r.system && <span className="rounded-full bg-muted px-2 py-0.5 text-[0.6875rem] font-semibold text-muted-foreground">built-in</span>}
              </button>
            </li>
          );
        })}
        {current?.mode === "new" && (
          <li className="flex items-center gap-3 bg-primary-soft px-4 py-3 text-sm font-semibold text-primary">
            <Plus className="size-4" aria-hidden /> {current.from ? `Copy of ${current.from.name}` : "New role"}
          </li>
        )}
      </ul>
    </Card>
  );
}

function RoleEditor({
  data,
  role,
  from,
  onSaved,
  onCopy,
  onError,
}: {
  data: RolesResponse;
  role?: AccessRole;
  from?: AccessRole;
  onSaved: (r: AccessRole | null, text: string) => void;
  onCopy: (r: AccessRole) => void;
  onError: (text: string) => void;
}) {
  const keys = data.pages.map((p) => p.key);
  const base = role ?? from;
  const [d, setD] = useState<Draft>(() => ({
    name: role ? role.name : from ? `${from.name} copy` : "",
    description: base?.description ?? "",
    pages: base ? { ...emptyPages(keys), ...base.pages } : emptyPages(keys),
    laptopHome: base?.laptopHome ?? "",
    phoneHome: base?.phoneHome ?? "",
  }));
  const [busy, setBusy] = useState(false);
  const groups = useMemo(() => {
    const out: { group: string; items: RolesResponse["pages"] }[] = [];
    for (const p of data.pages) {
      const g = out.find((x) => x.group === p.group);
      if (g) g.items.push(p);
      else out.push({ group: p.group, items: [p] });
    }
    return out;
  }, [data.pages]);
  const label = (k: PageKey) => data.pages.find((p) => p.key === k)?.label ?? k;
  const shown = (dev: keyof PageAccess) => keys.filter((k) => d.pages[k]?.[dev]);
  const setPage = (k: PageKey, dev: keyof PageAccess, on: boolean) =>
    setD((x) => {
      const pages = { ...x.pages, [k]: { ...x.pages[k], [dev]: on } };
      // a start page that is no longer shown on that device is cleared (the server picks the first shown page)
      const home = dev === "laptop" ? "laptopHome" : "phoneHome";
      return { ...x, pages, [home]: !on && x[home] === k ? "" : x[home] };
    });
  const setAll = (dev: keyof PageAccess, on: boolean) =>
    setD((x) => ({ ...x, pages: Object.fromEntries(keys.map((k) => [k, { ...x.pages[k], [dev]: on }])) as Record<PageKey, PageAccess>, ...(on ? {} : dev === "laptop" ? { laptopHome: "" } : { phoneHome: "" }) }));
  const nothing = !keys.some((k) => d.pages[k].laptop || d.pages[k].phone);
  const invalid = d.name.trim().length < 2 || nothing;

  const save = async () => {
    setBusy(true);
    try {
      const body = { name: d.name.trim(), description: d.description.trim() || null, pages: d.pages, laptopHome: d.laptopHome || null, phoneHome: d.phoneHome || null };
      const r = role ? await adminApi.updateRole(role.id, body) : await adminApi.createRole(body);
      onSaved(r, role ? `Role "${r.name}" saved – it applies to its ${r.users} user${r.users === 1 ? "" : "s"} at once.` : `Role "${r.name}" created. Give it to users in User Management.`);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Could not save the role");
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!role || !window.confirm(`Delete the role "${role.name}"?`)) return;
    setBusy(true);
    try {
      await adminApi.deleteRole(role.id);
      onSaved(null, `Role "${role.name}" deleted.`);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Could not delete the role");
      setBusy(false);
    }
  };

  return (
    <Card className="min-w-0 p-0">
      <div className="flex flex-wrap items-start gap-3 border-b border-border px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-bold">{role ? role.name : from ? `New role – copy of ${from.name}` : "New role"}</h2>
          <p className="mt-0.5 text-[0.8125rem] text-muted-foreground">
            {role ? (
              <>
                {role.system ? "Built-in role – edit its pages freely (it cannot be deleted). " : ""}
                <Link href="/dashboard/users" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
                  <Users className="size-3.5" aria-hidden /> {role.users} user{role.users === 1 ? "" : "s"}
                </Link>
                {role.updatedBy ? ` · last changed by ${role.updatedBy}` : ""}
              </>
            ) : (
              "Choose its pages for the laptop and the phone, then save."
            )}
          </p>
        </div>
        {role && (
          <Button variant="outline" size="sm" onClick={() => onCopy(role)} disabled={busy}>
            <Copy /> Copy role
          </Button>
        )}
        {role && !role.system && (
          <Button variant="outline" size="sm" className="border-critical/40 text-critical-text" onClick={remove} disabled={busy || role.users > 0} title={role.users > 0 ? "Give its users another role first" : "Delete this role"}>
            <Trash2 /> Delete
          </Button>
        )}
      </div>

      <div className="grid gap-4 px-5 py-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="role-name">Role name</Label>
          <Input id="role-name" value={d.name} maxLength={60} onChange={(e) => setD({ ...d, name: e.target.value })} placeholder="e.g. Circle Head" disabled={busy} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="role-desc">Description (optional)</Label>
          <Input id="role-desc" value={d.description} maxLength={300} onChange={(e) => setD({ ...d, description: e.target.value })} placeholder="Who gets this role" disabled={busy} />
        </div>
      </div>

      <div className="overflow-x-auto border-y border-border">
        <table className="w-full min-w-[30rem] text-sm">
          <thead className="bg-muted/50 text-[0.75rem] uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-5 py-2.5 text-left font-semibold">Page</th>
              <th className="w-32 px-3 py-2.5 text-center font-semibold">
                <span className="inline-flex items-center gap-1.5">
                  <Laptop className="size-3.5" aria-hidden /> Laptop
                </span>
              </th>
              <th className="w-32 px-3 py-2.5 text-center font-semibold">
                <span className="inline-flex items-center gap-1.5">
                  <Smartphone className="size-3.5" aria-hidden /> Phone
                </span>
              </th>
            </tr>
            <tr className="border-t border-border normal-case tracking-normal">
              <td className="px-5 py-1.5 text-[0.75rem] text-muted-foreground">Every page</td>
              {(["laptop", "phone"] as const).map((dev) => (
                <td key={dev} className="px-3 py-1.5 text-center text-[0.75rem]">
                  <button type="button" className="font-medium text-primary hover:underline disabled:opacity-50" onClick={() => setAll(dev, true)} disabled={busy}>
                    All
                  </button>
                  {" · "}
                  <button type="button" className="font-medium text-primary hover:underline disabled:opacity-50" onClick={() => setAll(dev, false)} disabled={busy}>
                    None
                  </button>
                </td>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => (
              <RoleGroup key={g.group} group={g.group} items={g.items} d={d} busy={busy} setPage={setPage} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 px-5 py-4 sm:grid-cols-2">
        {(["laptop", "phone"] as const).map((dev) => {
          const opts = shown(dev);
          const key = dev === "laptop" ? "laptopHome" : "phoneHome";
          return (
            <div key={dev} className="space-y-1.5">
              <Label>{dev === "laptop" ? "Laptop – opens first after sign-in" : "Phone – opens first after sign-in"}</Label>
              <Select
                value={d[key] || "__first"}
                onValueChange={(v) => setD({ ...d, [key]: v === "__first" ? "" : (v as PageKey) })}
                options={[{ value: "__first", label: opts.length ? `First page (${label(opts[0])})` : "No page on this device" }, ...opts.map((k) => ({ value: k, label: label(k) }))]}
                ariaLabel={`${dev} start page`}
                className="w-full"
                disabled={busy || !opts.length}
              />
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center justify-end gap-3 border-t border-border px-5 py-3">
        {nothing && <span className="mr-auto text-[0.8125rem] text-warning-text">Choose at least one page.</span>}
        <Button onClick={save} disabled={busy || invalid}>
          {busy ? <Loader2 className="animate-spin" /> : <Save />} {role ? "Save role" : "Create role"}
        </Button>
      </div>
    </Card>
  );
}

function RoleGroup({
  group,
  items,
  d,
  busy,
  setPage,
}: {
  group: string;
  items: RolesResponse["pages"];
  d: Draft;
  busy: boolean;
  setPage: (k: PageKey, dev: keyof PageAccess, on: boolean) => void;
}) {
  return (
    <>
      <tr className="border-t border-border bg-muted/25">
        <td colSpan={3} className="px-5 py-1.5 text-[0.6875rem] font-semibold uppercase tracking-[0.08em] text-subheading">
          {group}
        </td>
      </tr>
      {items.map((p) => (
        <tr key={p.key} className="border-t border-border">
          <td className="px-5 py-2.5 font-medium">{p.label}</td>
          {(["laptop", "phone"] as const).map((dev) => (
            <td key={dev} className="px-3 py-2.5 text-center">
              <Switch checked={!!d.pages[p.key]?.[dev]} onCheckedChange={(on) => setPage(p.key, dev, on)} disabled={busy} aria-label={`${p.label} on the ${dev}`} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}
