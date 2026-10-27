"use client";

import { Loader2, Pencil, Plus, UserPlus, X } from "lucide-react";
import { useMemo, useState } from "react";
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
import { IS_LIVE, adminApi, type AppUser, type ScopeLevel, type UserLocations } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { formatDateTime } from "@/lib/utils/format";

const LEVELS: { value: ScopeLevel; label: string }[] = [
  { value: "circle", label: "Circle" },
  { value: "district", label: "District" },
  { value: "block", label: "Block" },
];
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Options per level, labelled with their parents so same-named districts / blocks stay distinguishable. */
function scopeOptions(loc: UserLocations | undefined): Record<ScopeLevel, SearchableOption[]> {
  const out: Record<ScopeLevel, SearchableOption[]> = { circle: [], district: [], block: [] };
  for (const c of loc?.circles ?? []) {
    out.circle.push({ value: c.id, label: c.name });
    for (const d of c.districts) {
      out.district.push({ value: d.id, label: `${d.name} (${c.name})` });
      for (const b of d.blocks) out.block.push({ value: b.id, label: `${b.name} (${d.name}, ${c.name})` });
    }
  }
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
        description="Dashboard accounts, roles and the circles / districts / blocks each viewer receives in the AMC Conversion e-mails."
        actions={
          <Button variant="primary" onClick={() => setEditing({ mode: "create" })} disabled={!IS_LIVE}>
            <UserPlus /> Add user
          </Button>
        }
      />

      <Card className="p-5">
        <p className="mb-4 text-[13px] text-muted-foreground">
          <b>Admin</b> – manages data, users and mail; e-mails cover every circle. <b>Viewer</b> – reads dashboards; e-mails cover only the areas
          assigned below. A viewer without an area receives no e-mail. Area Managers, SME, COH and CBH are taken from the Escalation Matrix and do
          not need an account.
        </p>
        {!IS_LIVE ? (
          <p className="text-sm text-muted-foreground">User management needs the live backend.</p>
        ) : users.error ? (
          <ErrorState error={users.error} onRetry={users.reload} />
        ) : !users.data ? (
          <TableSkeleton rows={5} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[780px] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  {["Name", "Email", "Role", "Areas (e-mail scope)", "Last sign-in", "Status", ""].map((c) => (
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
                    <td className="max-w-[320px] py-2.5 pr-3">
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
                              {s.level[0].toUpperCase()}: {s.label ?? s.id}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-warning-text">None – no e-mail</span>
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
  options: Record<ScopeLevel, SearchableOption[]>;
  hasData: boolean;
  onDone: (msg: string) => void;
}) {
  const user = editing.mode === "edit" ? editing.user : null;
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [role, setRole] = useState<"admin" | "viewer">(user?.role ?? "viewer");
  const [password, setPassword] = useState("");
  const [scopes, setScopes] = useState<{ level: ScopeLevel; id: string }[]>(user?.scopes.map((s) => ({ level: s.level, id: s.id })) ?? []);
  const [level, setLevel] = useState<ScopeLevel>("circle");
  const [pick, setPick] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const label = (l: ScopeLevel, id: string) => options[l].find((o) => o.value === id)?.label ?? user?.scopes.find((s) => s.level === l && s.id === id)?.label ?? id;
  const emailOk = EMAIL_RE.test(email.trim());
  const valid = name.trim().length >= 2 && emailOk && (user ? true : password.length > 0);

  const add = () => {
    if (pick && !scopes.some((s) => s.level === level && s.id === pick)) setScopes([...scopes, { level, id: pick }]);
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
          <DialogDescription className="text-[13px] text-muted-foreground">
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
          <legend className="px-1 text-sm font-semibold">Areas for the AMC Conversion e-mail</legend>
          {role === "admin" ? (
            <p className="text-sm text-muted-foreground">Admins receive every circle – no areas needed.</p>
          ) : !hasData ? (
            <p className="text-sm text-warning-text">Upload the master data first – areas come from the active data.</p>
          ) : (
            <>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                <div className="space-y-1 sm:w-32">
                  <span className="text-xs font-medium text-muted-foreground">Level</span>
                  <Select
                    ariaLabel="Area level"
                    className="w-full"
                    value={level}
                    onValueChange={(v) => {
                      setLevel(v as ScopeLevel);
                      setPick(undefined);
                    }}
                    options={LEVELS}
                  />
                </div>
                <SearchableSelect className="flex-1" label={LEVELS.find((l) => l.value === level)!.label} value={pick} onChange={setPick} options={options[level]} placeholder="Search…" />
                <Button type="button" variant="outline" onClick={add} disabled={!pick}>
                  <Plus /> Add
                </Button>
              </div>
              {scopes.length ? (
                <ul className="flex flex-wrap gap-1.5">
                  {scopes.map((s) => (
                    <li key={`${s.level}:${s.id}`} className="inline-flex items-center gap-1 rounded bg-primary-soft py-0.5 pl-2 pr-1 text-xs text-primary">
                      {LEVELS.find((l) => l.value === s.level)!.label}: {label(s.level, s.id)}
                      <button type="button" className="rounded p-0.5 hover:bg-primary/15" aria-label="Remove area" onClick={() => setScopes(scopes.filter((x) => x !== s))}>
                        <X className="size-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-warning-text">No area: this viewer will not receive the AMC Conversion e-mail.</p>
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
