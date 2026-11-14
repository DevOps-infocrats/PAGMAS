"use client";

import { Loader2, Pencil, Plus, Search, Upload, UserPlus, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { StatusBadge } from "@/components/feedback/badges";
import { ErrorState, TableSkeleton } from "@/components/feedback/states";
import { SearchableSelect, type SearchableOption } from "@/components/filters/searchable-select";
import { AdminGuard } from "@/components/layout/admin-guard";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { Card, Input, Label } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useSession } from "@/hooks/use-session";
import { IS_LIVE, adminApi, type AppUser, type UserGpOption, type UserLocations, type UserScopeLevel } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatDateTime } from "@/lib/utils/format";
import { ImportUsersDialog } from "./import-users-dialog";

/** Levels offered when adding an area (districts saved before stay valid and are shown, but not offered) */
const LEVELS: { value: UserScopeLevel; label: string }[] = [
  { value: "circle", label: "Circle" },
  { value: "block", label: "Block" },
  { value: "gp", label: "GP" },
];
const LEVEL_LABEL: Record<UserScopeLevel, string> = { circle: "Circle", district: "District", block: "Block", gp: "GP" };
type Scope = { level: UserScopeLevel; id: string };
type BlockOption = SearchableOption & { circleId: string };
interface AreaOptions {
  circles: SearchableOption[];
  blocks: BlockOption[];
  /** labels of every circle / district / block, for the chips */
  labels: Record<string, string>;
}
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Circle and block options (blocks know their circle, so the block list follows the chosen circles), labelled with
 * their parents so same-named blocks stay distinguishable. GPs are searched on the server (thousands of them). */
function scopeOptions(loc: UserLocations | undefined): AreaOptions {
  const out: AreaOptions = { circles: [], blocks: [], labels: {} };
  for (const c of loc?.circles ?? []) {
    out.circles.push({ value: c.id, label: c.name });
    out.labels[`circle:${c.id}`] = c.name;
    for (const d of c.districts) {
      out.labels[`district:${d.id}`] = `${d.name} (${c.name})`;
      for (const b of d.blocks) {
        const label = `${b.name} (${d.name}, ${c.name})`;
        out.blocks.push({ value: b.id, label, circleId: c.id });
        out.labels[`block:${b.id}`] = label;
      }
    }
  }
  out.blocks.sort((a, b) => a.label.localeCompare(b.label));
  return out;
}

export function UsersView() {
  return (
    <AdminGuard>
      <UsersContent />
    </AdminGuard>
  );
}

type Editing = { mode: "create" } | { mode: "edit"; user: AppUser } | null;

function UsersContent() {
  const { session } = useSession();
  const [tick, setTick] = useState(0);
  const users = useApiQuery(IS_LIVE ? `users:${tick}` : null, () => adminApi.listUsers());
  const locations = useApiQuery(IS_LIVE ? "user-locations" : null, () => adminApi.getUserLocations());
  const options = useMemo(() => scopeOptions(locations.data), [locations.data]);
  const [editing, setEditing] = useState<Editing>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [importing, setImporting] = useState(false);

  const toggle = async (u: AppUser) => {
    setMsg(null);
    try {
      await adminApi.updateUser(u.id, { isActive: !u.isActive });
      setMsg({ ok: true, text: `${u.name} ${u.isActive ? "deactivated" : "activated"}.` });
      setTick((n) => n + 1);
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Update failed" });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Administration" }, { label: "User Management" }]}
        title="User Management"
        description="Dashboard accounts, roles and the circles / blocks / GPs each viewer may see – on the dashboard and in the AMC Conversion e-mails."
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setImporting(true)} disabled={!IS_LIVE}>
              <Upload /> Import users
            </Button>
            <Button variant="primary" onClick={() => setEditing({ mode: "create" })} disabled={!IS_LIVE}>
              <UserPlus /> Add user
            </Button>
          </div>
        }
      />

      <Card className="p-5">
        <p className="mb-4 text-[0.8125rem] text-muted-foreground">
          <b>Admin</b> – manages data, users and mail; sees and receives every circle. <b>Viewer</b> – reads dashboards. A viewer with areas sees
          only those areas on every page, list and download, and receives the AMC Conversion e-mail for them. A viewer without an area sees every
          state but receives no e-mail. Area Managers, SME, COH and CBH are taken from the Escalation Matrix and do not need an account.
        </p>
        {!IS_LIVE ? (
          <p className="text-sm text-muted-foreground">User management needs the live backend.</p>
        ) : users.error ? (
          <ErrorState error={users.error} onRetry={users.reload} />
        ) : !users.data ? (
          <TableSkeleton rows={5} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[48.75rem] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  {["Name", "Email", "Role", "Areas (data access & e-mail)", "Last sign-in", "Status", ""].map((c) => (
                    <th key={c} scope="col" className="py-2 pr-3 font-medium">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.data.map((u) => (
                  <tr key={u.id} className="border-b border-border/60 align-top last:border-0">
                    <td className="py-2.5 pr-3 font-medium">{u.name}</td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{u.email}</td>
                    <td className="py-2.5 pr-3 capitalize">{u.role}</td>
                    <td className="max-w-[20rem] py-2.5 pr-3">
                      {u.role === "admin" ? (
                        <span className="text-muted-foreground">All circles</span>
                      ) : u.scopes.length ? (
                        <div className="flex flex-wrap gap-1">
                          {u.scopes.map((s) => (
                            <span
                              key={`${s.level}:${s.id}`}
                              title={s.valid ? undefined : "Not in the active data – ignored"}
                              className={cn("rounded px-1.5 py-0.5 text-xs", s.valid ? "bg-primary-soft text-primary" : "bg-warning-soft text-warning-text line-through")}
                            >
                              {LEVEL_LABEL[s.level] ?? s.level}: {s.label ?? s.id}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-warning-text">None – sees all states, no e-mail</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-3 text-muted-foreground">{u.lastLoginAt ? formatDateTime(u.lastLoginAt) : "Never"}</td>
                    <td className="py-2.5 pr-3">
                      {u.locked ? <StatusBadge tone="warning">Locked</StatusBadge> : u.isActive ? <StatusBadge tone="good">Active</StatusBadge> : <StatusBadge tone="neutral">Inactive</StatusBadge>}
                    </td>
                    <td className="whitespace-nowrap py-2.5 text-right">
                      <Button size="sm" variant="ghost" onClick={() => setEditing({ mode: "edit", user: u })} aria-label={`Edit ${u.name}`}>
                        <Pencil /> Edit
                      </Button>
                      {u.email !== session?.email && (
                        <Button size="sm" variant="outline" onClick={() => toggle(u)}>
                          {u.isActive ? "Deactivate" : "Activate"}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {msg && <p className={cn("mt-3 text-sm", msg.ok ? "text-good-text" : "text-critical-text")}>{msg.text}</p>}
      </Card>

      <Dialog open={editing != null} onOpenChange={(o) => !o && setEditing(null)}>
        {editing && (
          <UserDialog
            key={editing.mode === "edit" ? editing.user.id : "new"}
            editing={editing}
            self={editing.mode === "edit" && editing.user.email === session?.email}
            options={options}
            hasData={locations.data?.hasData ?? false}
            onDone={(text) => {
              setEditing(null);
              setMsg({ ok: true, text });
              setTick((n) => n + 1);
            }}
          />
        )}
      </Dialog>

      <Dialog open={importing} onOpenChange={setImporting}>
        {importing && (
          <ImportUsersDialog
            onDone={(text) => {
              setImporting(false);
              setMsg({ ok: true, text });
              setTick((n) => n + 1);
            }}
          />
        )}
      </Dialog>
    </div>
  );
}

function UserDialog({
  editing,
  self,
  options,
  hasData,
  onDone,
}: {
  editing: NonNullable<Editing>;
  self: boolean;
  options: AreaOptions;
  hasData: boolean;
  onDone: (msg: string) => void;
}) {
  const user = editing.mode === "edit" ? editing.user : null;
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState<"admin" | "viewer">(user?.role ?? "viewer");
  const [password, setPassword] = useState("");
  const [scopes, setScopes] = useState<Scope[]>(user?.scopes.map((s) => ({ level: s.level, id: s.id })) ?? []);
  const [level, setLevel] = useState<UserScopeLevel>("circle");
  const [pick, setPick] = useState<string | undefined>();
  const [gpLabels, setGpLabels] = useState<Record<string, string>>({}); // GPs picked in this dialog
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const label = (l: UserScopeLevel, id: string) =>
    (l === "gp" ? gpLabels[id] : options.labels[`${l}:${id}`]) ?? user?.scopes.find((s) => s.level === l && s.id === id)?.label ?? id;
  // the picker follows what is already chosen: blocks of the chosen circles; GPs of the chosen blocks, else circles
  const chosenCircles = scopes.filter((s) => s.level === "circle").map((s) => s.id);
  const chosenBlocks = scopes.filter((s) => s.level === "block").map((s) => s.id);
  const blockOptions = chosenCircles.length ? options.blocks.filter((b) => chosenCircles.includes(b.circleId)) : options.blocks;
  const pickOptions = level === "circle" ? options.circles : blockOptions;
  const emailOk = EMAIL_RE.test(email.trim());
  const valid = name.trim().length >= 2 && emailOk && (user ? true : password.length > 0);

  const addScope = (s: Scope) => {
    if (!scopes.some((x) => x.level === s.level && x.id === s.id)) setScopes([...scopes, s]);
  };
  const add = () => {
    if (pick) addScope({ level, id: pick });
    setPick(undefined);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const sc = role === "viewer" ? scopes : [];
      if (user) {
        await adminApi.updateUser(user.id, {
          name: name.trim(),
          ...(email.trim().toLowerCase() !== user.email ? { email: email.trim() } : {}),
          ...(self ? {} : { role }),
          ...(password ? { password } : {}),
          scopes: sc,
        });
        onDone(`${name.trim()} saved.`);
      } else {
        await adminApi.createUser({ name: name.trim(), email: email.trim(), role, password, scopes: sc });
        onDone(`User ${email.trim()} created.`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogContent className="max-w-xl">
      <form
        className="space-y-4 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && !busy) void save();
        }}
      >
        <div>
          <DialogTitle className="text-base font-bold">{user ? `Edit ${user.name}` : "Add user"}</DialogTitle>
          <DialogDescription className="text-[0.8125rem] text-muted-foreground">
            {user ? "Changing the e-mail, role or password signs the user out." : "The user signs in with this e-mail and password."}
          </DialogDescription>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field id="u-name" label="Full name" value={name} onChange={setName} />
          <Field id="u-email" label="Email address" type="email" value={email} onChange={setEmail} disabled={self} invalid={email.length > 0 && !emailOk} />
          <div className="space-y-1.5">
            <Label htmlFor="u-role">Role</Label>
            <Select
              ariaLabel="Role"
              className="w-full"
              value={role}
              disabled={self}
              onValueChange={(v) => setRole(v as "admin" | "viewer")}
              options={[
                { value: "viewer", label: "Viewer" },
                { value: "admin", label: "Admin" },
              ]}
            />
          </div>
          <Field id="u-pass" label={user ? "New password (optional)" : "Initial password"} type="password" value={password} onChange={setPassword} autoComplete="new-password" />
        </div>
        {self && <p className="text-xs text-muted-foreground">You cannot change your own role or e-mail address.</p>}

        <fieldset className="space-y-2 rounded-lg border border-border p-3">
          <legend className="px-1 text-sm font-semibold">Areas – data access & AMC Conversion e-mail</legend>
          {role === "admin" ? (
            <p className="text-sm text-muted-foreground">Admins see and receive every circle – no areas needed.</p>
          ) : !hasData ? (
            <p className="text-sm text-warning-text">Upload the master data first – areas come from the active data.</p>
          ) : (
            <>
              <div className={cn("flex flex-col gap-2 sm:flex-row", level === "gp" ? "sm:items-start" : "sm:items-end")}>
                <div className="space-y-1 sm:w-32">
                  <span className="text-xs font-medium text-muted-foreground">Level</span>
                  <Select
                    ariaLabel="Area level"
                    className="w-full"
                    value={level}
                    onValueChange={(v) => {
                      setLevel(v as UserScopeLevel);
                      setPick(undefined);
                    }}
                    options={LEVELS}
                  />
                </div>
                {level === "gp" ? (
                  <GpPicker
                    circles={chosenCircles}
                    blocks={chosenBlocks}
                    picked={new Set(scopes.filter((s) => s.level === "gp").map((s) => s.id))}
                    onPick={(gp) => {
                      setGpLabels((m) => ({ ...m, [gp.id]: gp.label }));
                      addScope({ level: "gp", id: gp.id });
                    }}
                  />
                ) : (
                  <>
                    <SearchableSelect className="flex-1" label={LEVEL_LABEL[level]} value={pick} onChange={setPick} options={pickOptions} placeholder="Search…" />
                    <Button type="button" variant="outline" onClick={add} disabled={!pick}>
                      <Plus /> Add
                    </Button>
                  </>
                )}
              </div>
              {level !== "circle" && (
                <p className="text-[0.75rem] text-muted-foreground">
                  {level === "block"
                    ? chosenCircles.length
                      ? `Blocks of ${chosenCircles.map((c) => label("circle", c)).join(", ")}.`
                      : "Every block – choose a circle first to see only its blocks."
                    : chosenBlocks.length
                      ? `GPs of the chosen block${chosenBlocks.length === 1 ? "" : "s"} only.`
                      : chosenCircles.length
                        ? `GPs of ${chosenCircles.map((c) => label("circle", c)).join(", ")}.`
                        : "Every GP – choose a circle or block first to narrow the list."}{" "}
                  A block or GP inside a chosen circle limits the access to it.
                </p>
              )}
              {scopes.length ? (
                <ul className="flex flex-wrap gap-1.5">
                  {scopes.map((s) => (
                    <li key={`${s.level}:${s.id}`} className="inline-flex items-center gap-1 rounded bg-primary-soft py-0.5 pl-2 pr-1 text-xs text-primary">
                      {LEVEL_LABEL[s.level] ?? s.level}: {label(s.level, s.id)}
                      <button type="button" className="rounded p-0.5 hover:bg-primary/15" aria-label="Remove area" onClick={() => setScopes(scopes.filter((x) => x !== s))}>
                        <X className="size-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-warning-text">No area: this viewer sees every state and will not receive the AMC Conversion e-mail.</p>
              )}
            </>
          )}
        </fieldset>

        {error && <p className="text-sm text-critical-text">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="submit" variant="primary" disabled={!valid || busy}>
            {busy && <Loader2 className="animate-spin" />} {user ? "Save" : "Create user"}
          </Button>
        </div>
      </form>
    </DialogContent>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  disabled,
  invalid,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  autoComplete?: string;
  disabled?: boolean;
  invalid?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type={type} value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete} maxLength={128} disabled={disabled} aria-invalid={invalid || undefined} />
    </div>
  );
}

/** GP area picker: GPs are searched on the server (thousands of them) – those of the chosen blocks, else of the chosen
 * circles, else all – by GP name or code; a click adds the GP. */
function GpPicker({ circles, blocks, picked, onPick }: { circles: string[]; blocks: string[]; picked: Set<string>; onPick: (gp: UserGpOption) => void }) {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250);
    return () => clearTimeout(t);
  }, [text]);
  const scope = blocks.length ? `b:${blocks.join(",")}` : `c:${circles.join(",")}`;
  const res = useApiQuery(`user-gps:${scope}:${q}`, () => adminApi.searchUserGps({ circles, blocks, q, limit: 50 }));
  const items = res.data?.items ?? [];
  return (
    <div className="min-w-0 flex-1 space-y-1">
      <span className="text-xs font-medium text-muted-foreground">GP</span>
      <span className="relative block">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden />
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Search GP name or code…" maxLength={80} className="pl-8" aria-label="Search GP" />
      </span>
      <div className="max-h-44 overflow-auto rounded-md border border-border">
        {res.error ? (
          <p className="px-2.5 py-2 text-xs text-critical-text">{res.error.message}</p>
        ) : !res.data ? (
          <p className="px-2.5 py-2 text-xs text-muted-foreground">Loading GPs…</p>
        ) : items.length === 0 ? (
          <p className="px-2.5 py-2 text-xs text-muted-foreground">No GP found.</p>
        ) : (
          <ul>
            {items.map((gp) => {
              const added = picked.has(gp.id);
              return (
                <li key={gp.id}>
                  <button
                    type="button"
                    disabled={added}
                    onClick={() => onPick(gp)}
                    className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-xs hover:bg-accent disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent"
                  >
                    <span className="truncate">{gp.label}</span>
                    {added ? <span className="shrink-0 text-[0.6875rem] font-semibold text-primary">added</span> : <Plus className="size-3.5 shrink-0 text-primary" aria-hidden />}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {res.data && res.data.total > items.length && (
        <p className="text-[0.6875rem] text-muted-foreground">
          Showing {items.length} of {res.data.total.toLocaleString("en-IN")} GPs – type a name or code to narrow.
        </p>
      )}
    </div>
  );
}
