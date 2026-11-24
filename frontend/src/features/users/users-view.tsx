"use client";

import { Loader2, Plus, Search, Upload, UserPlus, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ErrorState, TableSkeleton } from "@/components/feedback/states";
import { SearchableSelect, type SearchableOption } from "@/components/filters/searchable-select";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { Card, Input, Label } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useSession } from "@/hooks/use-session";
import { IS_LIVE, adminApi, type AccessRole, type AppUser, type UserGpOption, type UserLocations, type UserScopeLevel } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { ImportUsersDialog } from "./import-users-dialog";
import { RolesHelp, UsersTable } from "./users-table-parts";

/** Levels offered when adding an area */
const LEVELS: { value: UserScopeLevel; label: string }[] = [
  { value: "circle", label: "Circle" },
  { value: "ba", label: "BA" },
  { value: "district", label: "District" },
  { value: "block", label: "Block" },
  { value: "gp", label: "GP" },
];
const LEVEL_LABEL: Record<UserScopeLevel, string> = { circle: "Circle", ba: "BA", district: "District", block: "Block", gp: "GP" };
type Scope = { level: UserScopeLevel; id: string };
type BlockOption = SearchableOption & { circleId: string };
/** a BA / district: its circle and the ids of its blocks (so the block list follows it) */
type GroupOption = SearchableOption & { circleId: string; blocks: string[] };
interface AreaOptions {
  circles: SearchableOption[];
  bas: GroupOption[];
  districts: GroupOption[];
  blocks: BlockOption[];
  /** labels of every circle / BA / district / block, for the chips */
  labels: Record<string, string>;
}
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Circle, BA, district and block options (each knows its circle; BAs and districts know their blocks, so the lists
 * follow what is chosen above them), labelled with their parents so same-named places stay distinguishable. GPs are
 * searched on the server (thousands of them). */
function scopeOptions(loc: UserLocations | undefined): AreaOptions {
  const out: AreaOptions = { circles: [], bas: [], districts: [], blocks: [], labels: {} };
  for (const c of loc?.circles ?? []) {
    out.circles.push({ value: c.id, label: c.name });
    out.labels[`circle:${c.id}`] = c.name;
    for (const b of c.bas ?? []) {
      const label = `${b.name} BA (${c.name})`;
      out.bas.push({ value: b.id, label, circleId: c.id, blocks: b.blocks });
      out.labels[`ba:${b.id}`] = label;
    }
    for (const d of c.districts) {
      out.labels[`district:${d.id}`] = `${d.name} (${c.name})`;
      out.districts.push({ value: d.id, label: `${d.name} (${c.name})`, circleId: c.id, blocks: d.blocks.map((b) => b.id) });
      for (const b of d.blocks) {
        const label = `${b.name} (${d.name}, ${c.name})`;
        out.blocks.push({ value: b.id, label, circleId: c.id });
        out.labels[`block:${b.id}`] = label;
      }
    }
  }
  out.blocks.sort((a, b) => a.label.localeCompare(b.label));
  out.bas.sort((a, b) => a.label.localeCompare(b.label));
  out.districts.sort((a, b) => a.label.localeCompare(b.label));
  return out;
}

export function UsersView() {
  return (
    <>
      <UsersContent />
    </>
  );
}

type Editing = { mode: "create" } | { mode: "edit"; user: AppUser } | null;

function UsersContent() {
  const { session, isAdmin } = useSession();
  const [tick, setTick] = useState(0);
  const users = useApiQuery(IS_LIVE ? `users:${tick}` : null, () => adminApi.listUsers());
  const locations = useApiQuery(IS_LIVE ? "user-locations" : null, () => adminApi.getUserLocations());
  const roles = useApiQuery(IS_LIVE ? `roles:${tick}` : null, () => adminApi.listRoles()); // Roles & Access
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

  const remove = async (u: AppUser) => {
    if (!window.confirm(`Delete the user "${u.name}" (${u.email}) permanently?

The account and its areas are removed. Tickets and history stay. This cannot be undone – use Deactivate to only block the sign-in.`)) return;
    setMsg(null);
    try {
      await adminApi.deleteUser(u.id);
      setMsg({ ok: true, text: `${u.name} deleted.` });
      setTick((n) => n + 1);
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Delete failed" });
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

      <Card className="space-y-4 p-5">
        <RolesHelp />
        {!IS_LIVE ? (
          <p className="text-sm text-muted-foreground">User management needs the live backend.</p>
        ) : users.error ? (
          <ErrorState error={users.error} onRetry={users.reload} />
        ) : !users.data ? (
          <TableSkeleton rows={5} />
        ) : (
          <UsersTable
            users={users.data}
            locations={locations.data}
            selfEmail={session?.email}
            canEditAdmins={isAdmin}
            onEdit={(u) => setEditing({ mode: "edit", user: u })}
            onToggle={(u) => void toggle(u)}
            onRemove={(u) => void remove(u)}
          />
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
            roles={roles.data?.roles ?? []}
            canMakeAdmin={isAdmin}
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
  roles,
  canMakeAdmin,
  onDone,
}: {
  editing: NonNullable<Editing>;
  self: boolean;
  options: AreaOptions;
  hasData: boolean;
  roles: AccessRole[];
  /** only an admin adds / promotes admin accounts (a User Management role without admin cannot – the server checks too) */
  canMakeAdmin: boolean;
  onDone: (msg: string) => void;
}) {
  const user = editing.mode === "edit" ? editing.user : null;
  const [name, setName] = useState(user?.name ?? "");
  // FRT team login without e-mail: the user signs in with the FRT code (app.security.frt_login on the backend)
  const [byCode, setByCode] = useState(user?.loginType === "frt");
  const [email, setEmail] = useState(user?.loginType === "frt" ? "" : (user?.email ?? ""));
  // Role select: "admin", "default" (the built-in Viewer role – roleId null) or "role:<id>" (an access role)
  const viewerRole = roles.find((r) => r.key === "viewer");
  const valueOf = (id: number | null | undefined) => (id == null || id === viewerRole?.id ? "default" : `role:${id}`);
  const initialRoleId = user && user.role !== "admin" ? (user.roleId ?? null) : null;
  const [access, setAccess] = useState<string>(user?.role === "admin" ? "admin" : valueOf(initialRoleId));
  const role: "admin" | "viewer" = access === "admin" ? "admin" : "viewer";
  const roleId = access.startsWith("role:") ? Number(access.slice(5)) : null;
  const frtRole = roles.find((r) => r.key === "frt");
  const [password, setPassword] = useState("");
  // FRT team login: the Escalation Matrix FRT code this viewer reports the Daily Achievement for ("" = not an FRT)
  const [frtCode, setFrtCode] = useState(user?.frtCode ?? "");
  const [scopes, setScopes] = useState<Scope[]>(user?.scopes.map((s) => ({ level: s.level, id: s.id })) ?? []);
  const [level, setLevel] = useState<UserScopeLevel>("circle");
  const [pick, setPick] = useState<string | undefined>();
  const [gpLabels, setGpLabels] = useState<Record<string, string>>({}); // GPs picked in this dialog
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const label = (l: UserScopeLevel, id: string) =>
    (l === "gp" ? gpLabels[id] : options.labels[`${l}:${id}`]) ?? user?.scopes.find((s) => s.level === l && s.id === id)?.label ?? id;
  // the picker follows what is already chosen: BAs / districts of the chosen circles; blocks of the chosen BAs /
  // districts, else circles; GPs of the chosen blocks, else BAs / districts, else circles
  const chosen = (l: UserScopeLevel) => scopes.filter((s) => s.level === l).map((s) => s.id);
  const chosenCircles = chosen("circle");
  const chosenBas = chosen("ba");
  const chosenDistricts = chosen("district");
  const chosenBlocks = chosen("block");
  const inCircles = <T extends { circleId: string }>(list: T[]) => (chosenCircles.length ? list.filter((x) => chosenCircles.includes(x.circleId)) : list);
  const groupBlocks = new Set([...options.bas.filter((b) => chosenBas.includes(b.value)), ...options.districts.filter((d) => chosenDistricts.includes(d.value))].flatMap((x) => x.blocks));
  const blockOptions = groupBlocks.size ? options.blocks.filter((b) => groupBlocks.has(b.value)) : inCircles(options.blocks);
  const pickOptions = level === "circle" ? options.circles : level === "ba" ? inCircles(options.bas) : level === "district" ? inCircles(options.districts) : blockOptions;
  const chosenGroups = [...chosenBas.map((i) => label("ba", i)), ...chosenDistricts.map((i) => label("district", i))];
  const emailOk = EMAIL_RE.test(email.trim());
  const codeOk = frtCode.trim().length >= 2;
  const valid = name.trim().length >= 2 && (byCode ? codeOk && role === "viewer" : emailOk) && (user ? true : password.length > 0);

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
      const frt = role === "viewer" ? frtCode.trim() : "";
      if (user) {
        // a code-only FRT login keeps its (non-deliverable) login address unless an e-mail is given now
        const newEmail = byCode ? null : email.trim().toLowerCase() !== user.email ? email.trim() : null;
        await adminApi.updateUser(user.id, {
          name: name.trim(),
          ...(newEmail ? { email: newEmail } : {}),
          ...(self ? {} : { role }),
          ...(!self && role === "viewer" && roleId !== (valueOf(initialRoleId) === "default" ? null : initialRoleId) ? { roleId } : {}),
          ...(password ? { password } : {}),
          scopes: sc,
          ...(frt !== (user.frtCode ?? "") ? { frtCode: frt } : {}),
        });
        onDone(`${name.trim()} saved.`);
      } else {
        await adminApi.createUser({ name: name.trim(), ...(byCode ? {} : { email: email.trim() }), role, password, scopes: sc, ...(frt ? { frtCode: frt } : {}), ...(roleId ? { roleId } : {}) });
        onDone(byCode ? `FRT login ${frt.toUpperCase()} created – the user signs in with the FRT code and the password.` : `User ${email.trim()} created.`);
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
            {user ? "Changing the e-mail, role, FRT code or password signs the user out." : byCode ? "The FRT signs in with the FRT code and this password." : "The user signs in with this e-mail and password."}
          </DialogDescription>
        </div>
        {!self && (
          <div className="flex flex-wrap items-center gap-3 text-[0.8125rem]" role="radiogroup" aria-label="Login with">
            <span className="font-medium">Login with</span>
            <label className="inline-flex cursor-pointer items-center gap-1.5">
              <input type="radio" name="login-by" checked={!byCode} onChange={() => setByCode(false)} className="accent-[var(--primary)]" /> E-mail
            </label>
            <label className="inline-flex cursor-pointer items-center gap-1.5">
              <input type="radio" name="login-by" checked={byCode} onChange={() => { setByCode(true); if (access === "admin" || (!user && access === "default")) setAccess(frtRole ? `role:${frtRole.id}` : "default"); }} className="accent-[var(--primary)]" /> FRT code (no e-mail)
            </label>
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field id="u-name" label="Full name" value={name} onChange={setName} />
          {byCode ? (
            <div className="space-y-1">
              <Field id="u-frt-login" label="FRT code (login name)" value={frtCode} onChange={setFrtCode} invalid={frtCode.length > 0 && !codeOk} />
              <p className="text-xs text-muted-foreground">Exactly as in the Escalation Matrix – checked when you save. One such login per FRT code.</p>
            </div>
          ) : (
            <Field id="u-email" label="Email address" type="email" value={email} onChange={setEmail} disabled={self} invalid={email.length > 0 && !emailOk} />
          )}
          <div className="space-y-1.5">
            <Label htmlFor="u-role">Role</Label>
            <Select
              ariaLabel="Role"
              className="w-full"
              value={access}
              disabled={self}
              onValueChange={setAccess}
              options={[
                ...(byCode || !canMakeAdmin ? [] : [{ value: "admin", label: "Admin – every page" }]),
                { value: "default", label: viewerRole ? `${viewerRole.name} (default)` : "Viewer (default)" },
                ...roles.filter((r) => r.key !== "viewer").map((r) => ({ value: `role:${r.id}`, label: r.name })),
              ]}
            />
            <p className="text-[0.6875rem] text-muted-foreground">The role decides the pages (Roles &amp; Access); the areas below decide the data.</p>
          </div>
          <Field id="u-pass" label={user ? "New password (optional)" : "Initial password"} type="password" value={password} onChange={setPassword} autoComplete="new-password" />
        </div>
        {self && <p className="text-xs text-muted-foreground">You cannot change your own role or e-mail address.</p>}
        {role === "viewer" && !byCode && (
          <div className="space-y-1.5">
            <Field id="u-frt" label="FRT code (FRT team login – optional)" value={frtCode} onChange={setFrtCode} />
            <p className="text-xs text-muted-foreground">
              Fill in only for an FRT team: the code exactly as in the Escalation Matrix (FRT Code column). The FRT then reports the Daily Achievement of those GPs in
              the GP-wise tickets; their FE verifies it before the Area Manager. Leave empty for everyone else.
            </p>
          </div>
        )}

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
                    bas={chosenBas}
                    districts={chosenDistricts}
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
                  {level === "ba" || level === "district"
                    ? chosenCircles.length
                      ? `${level === "ba" ? "BAs" : "Districts"} of ${chosenCircles.map((c) => label("circle", c)).join(", ")}.`
                      : `Every ${level === "ba" ? "BA" : "district"} – choose a circle first to see only its ${level === "ba" ? "BAs" : "districts"}.`
                    : level === "block"
                      ? chosenGroups.length
                        ? `Blocks of ${chosenGroups.join(", ")}.`
                        : chosenCircles.length
                          ? `Blocks of ${chosenCircles.map((c) => label("circle", c)).join(", ")}.`
                          : "Every block – choose a circle, BA or district first to see only its blocks."
                      : chosenBlocks.length
                        ? `GPs of the chosen block${chosenBlocks.length === 1 ? "" : "s"} only.`
                        : chosenGroups.length
                          ? `GPs of ${chosenGroups.join(", ")}.`
                          : chosenCircles.length
                            ? `GPs of ${chosenCircles.map((c) => label("circle", c)).join(", ")}.`
                            : "Every GP – choose a circle, BA, district or block first to narrow the list."}{" "}
                  A BA, district, block or GP inside a chosen area limits the access to it.
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
 * BAs / districts, else circles, else all – by GP name or code; a click adds the GP. */
function GpPicker({
  circles,
  bas,
  districts,
  blocks,
  picked,
  onPick,
}: {
  circles: string[];
  bas: string[];
  districts: string[];
  blocks: string[];
  picked: Set<string>;
  onPick: (gp: UserGpOption) => void;
}) {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250);
    return () => clearTimeout(t);
  }, [text]);
  const scope = blocks.length ? `b:${blocks.join(",")}` : bas.length || districts.length ? `g:${bas.join(",")}|${districts.join(",")}` : `c:${circles.join(",")}`;
  const res = useApiQuery(`user-gps:${scope}:${q}`, () => adminApi.searchUserGps({ circles, bas, districts, blocks, q, limit: 50 }));
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
