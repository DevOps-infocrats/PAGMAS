"use client";

import { ChevronDown, Loader2, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import { ErrorState } from "@/components/feedback/states";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { useMeta } from "@/components/providers/data-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { Input, Label } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { ticketApi, type DirectoryFe, type DirectoryPerson, type TaskFigures, type TaskPreviewRow, type TicketAssignee, type TicketDirectory, type TicketPriority } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { PRIORITY_META, TEXTAREA } from "./ticket-parts";

type Role = "COH" | "SME" | "AM" | "FE" | "OTHER";
type Account = { id: number; name: string } | null;
interface Picked {
  role: Role;
  name: string;
  email: string;
  account: Account;
  /** FE: parent Area Manager and the matrix FE e-mail of their GPs (decides which GPs the FE gets) */
  am?: string;
  mapped?: string | null;
  /** typed by the admin (nobody / not this person in the matrix): AM = acting AM of the GPs without an AM; FE = gets
   * the GPs without an FE of the Area Manager `am` */
  typed?: boolean;
  /** AM of the matrix who also takes the circle's GPs without an Area Manager (and their FEs) */
  withNoAm?: boolean;
}

/** The group of a circle's GPs without an Area Manager in the matrix (backend task.NO_AM). */
const NO_AM = "No Area Manager";

/** FEs stay only while their Area Manager is selected (none once every Area Manager is removed); FEs of GPs without an
 * Area Manager stay (they go FE-wise or to the AM who takes those GPs). */
const pruneFes = (list: Picked[]) => {
  const ams = new Set(list.filter((p) => p.role === "AM").map((p) => p.name));
  return list.filter((p) => p.role !== "FE" || (p.am != null && (ams.has(p.am) || (!p.typed && p.am === NO_AM))));
};
const feKey = (f: { name: string; mappedEmail?: string | null; mapped?: string | null }) => `${f.name.toLowerCase().replace(/[^a-z0-9]/g, "")}|${(f.mappedEmail ?? f.mapped ?? "").toLowerCase()}`;

const PRIORITIES = (Object.keys(PRIORITY_META) as TicketPriority[]).map((p) => ({ value: p, label: PRIORITY_META[p].label }));
const OTHER = "__other";
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const ROLE_TITLE: Record<Role, string> = { COH: "COH", SME: "SME", AM: "Area Manager", FE: "Field Engineer", OTHER: "Other recipient" };

/**
 * Generate Ticket (admin). Circle / State first: its SME, COH and Area Managers come from the database (Escalation
 * Matrix). Each role is optional and several people can be added; e-mails are picked from the database or typed.
 * People with a dashboard account see the ticket in User Tickets; the optional e-mail goes to the selected people only.
 * GP-wise Task Assignment: one ticket + Excel per selected Area Manager with only that AM's GPs of the week.
 */
export function GenerateTicketDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onCreated: (r: { codes: string[]; emailQueued: number }) => void;
}) {
  const meta = useMeta();
  const [circle, setCircle] = useState<string | undefined>(undefined);
  const [taskOn, setTaskOn] = useState(false);
  const [taskWeek, setTaskWeek] = useState<string | undefined>(undefined);
  const week = taskWeek ?? meta?.latestWeekId;
  const dir = useApiQuery(open && week ? `ticket-dir:${circle ?? ""}:${week}` : null, () => ticketApi.getDirectory(circle ?? null, week));
  const d = dir.data ?? dir.staleData;
  const here = d && d.circle === (circle ?? null) ? d : undefined; // people of the selected circle only
  const users = useApiQuery(open ? "ticket-assignees" : null, () => ticketApi.listAssignees());
  const accounts = useMemo(() => new Map((users.data ?? []).map((u) => [u.email.toLowerCase(), u] as const)), [users.data]);

  const [picked, setPicked] = useState<Picked[]>([]);
  const [otherUserId, setOtherUserId] = useState<number | null>(null);
  const [sendEmail, setSendEmail] = useState(false);
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TicketPriority | "">("");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const circleOptions = useMemo(() => (d?.circles ?? []).map((c) => ({ value: c.name, label: c.name, hint: `${c.gps.toLocaleString("en-IN")} GPs` })), [d?.circles]);
  const weekOptions = useMemo(() => [...(meta?.weeks ?? [])].reverse().map((w) => ({ value: w.id, label: w.label })), [meta?.weeks]);
  const userOptions = useMemo(() => (users.data ?? []).map((u) => ({ value: String(u.id), label: u.name, hint: u.email })), [users.data]);
  const otherUser: TicketAssignee | undefined = users.data?.find((u) => u.id === otherUserId);
  const pickedAms = picked.filter((p) => p.role === "AM");
  const pickedFes = picked.filter((p) => p.role === "FE");
  const amNames = new Set(pickedAms.map((a) => a.name));
  const noAm = here?.noAm ?? null;
  // the one Area Manager who takes the circle's GPs without an AM: the acting AM typed by the admin or a matrix AM ticked for it
  const owner = taskOn ? pickedAms.find((a) => a.typed || a.withNoAm) : undefined;
  /** the Area Manager whose ticket an FE is on (same rule as the backend) */
  const home = (f: Picked) => (f.typed ? f.am : f.am === NO_AM && owner ? owner.name : f.am);
  const feOnlyAms = [...new Set(pickedFes.map(home).filter((h): h is string => !!h && !amNames.has(h)))];
  const weekLabel = week?.replace("W-", "Week ");

  const add = (p: Picked) => {
    setPicked((cur) => (p.role === "AM" ? pruneFes([...cur, p]) : [...cur, p]));
    if ((p.role === "AM" || p.role === "FE") && taskOn) autofill(p.role === "AM" ? p.name : `FE ${p.name}`);
  };
  const remove = (email: string) =>
    setPicked((cur) => {
      const gone = cur.find((p) => p.email === email);
      const next = cur.filter((p) => p.email !== email);
      return gone?.role === "AM" ? pruneFes(next) : next; // an Area Manager's FEs go with them
    });
  const autofill = (am: string) => {
    if (!subject.trim()) setSubject(`Weekly GP task – ${am} – ${weekLabel}`);
    if (!description.trim()) setDescription(`Convert the GPs of ${weekLabel} assigned in the attached Excel and submit your progress daily in this ticket (achieved GPs and remarks).`);
  };

  const amRow = (name: string) => here?.am.find((a) => a.name === name);
  const feRow = (f: Picked) => here?.fe.find((x) => x.am === f.am && feKey(x) === feKey(f));
  // no target GP in the week: the ticket is still created (0 GPs – the FE can add GPs found in the field)
  const noGps = taskOn
    ? [
        ...pickedAms.filter((a) => (a.typed ? (noAm?.weekGps ?? 0) === 0 : !a.withNoAm && (amRow(a.name)?.weekGps ?? 1) === 0)),
        ...pickedFes.filter((f) => !f.typed && (feRow(f)?.weekGps ?? 1) === 0),
      ]
    : [];
  // the week's target GPs without an Area Manager that no ticket gets (nobody takes them and their FE is not selected)
  const leftover = (() => {
    if (!taskOn || !noAm || owner) return null;
    const fes = (here?.fe ?? []).filter((f) => f.am === NO_AM && f.weekGps > 0 && !pickedFes.some((p) => p.am === NO_AM && feKey(p) === feKey(f)));
    const gps = fes.reduce((n, f) => n + f.weekGps, 0) + noAm.unmappedFeGps;
    return gps > 0 ? { fes: fes.length, gps } : null;
  })();
  const withAccount = picked.some((p) => p.account) || !!otherUser;
  const amsWithoutAccount = [...pickedAms, ...pickedFes].filter((a) => !a.account);
  const ticketCount = taskOn ? pickedAms.length + feOnlyAms.length : 1;
  const problems = {
    circle: !circle ? "Select the Circle / State" : null,
    recipients: picked.length === 0 && !otherUser ? "Select at least one SME, COH, Area Manager, Field Engineer, dashboard user or type an e-mail" : null,
    task: !taskOn
      ? null
      : pickedAms.length === 0 && pickedFes.length === 0
        ? "Add at least one Area Manager or Field Engineer for the GP-wise task"
        : null,
    reach: sendEmail
      ? null
      : taskOn && amsWithoutAccount.length
        ? `${amsWithoutAccount.map((a) => a.name).join(", ")}: no dashboard account – turn on "Send Email Notification" or add the user in User Management`
        : picked.length + (otherUser ? 1 : 0) > 0 && !withAccount
          ? 'None of the selected people has a dashboard account – turn on "Send Email Notification" or add a registered user'
          : null,
    subject: subject.trim().length < 3 ? "Enter a subject (at least 3 characters)" : null,
    description: description.trim().length < 10 ? "Describe the work (at least 10 characters)" : null,
    priority: !priority ? "Choose a priority" : null,
  };
  const valid = !Object.values(problems).some(Boolean);

  const reset = () => {
    setCircle(undefined);
    setTaskOn(false);
    setTaskWeek(undefined);
    setPicked([]);
    setOtherUserId(null);
    setSendEmail(false);
    setSubject("");
    setDescription("");
    setPriority("");
    setTouched(false);
    setError(null);
  };

  const submit = async () => {
    setTouched(true);
    if (!valid || !priority || !circle) return;
    setBusy(true);
    setError(null);
    try {
      const r = await ticketApi.create({
        circle,
        recipients: picked.map(({ role, name, email, am, mapped, typed, withNoAm }) =>
          role === "FE"
            ? { role, name, email, am, feEmail: mapped ?? null, ...(typed ? { typed } : {}) }
            : { role, name, email, ...(typed ? { typed } : {}), ...(withNoAm && taskOn ? { withNoAm } : {}) },
        ),
        assigneeId: otherUser?.id ?? null,
        sendEmail,
        subject: subject.trim(),
        description: description.trim(),
        priority,
        ...(taskOn && week ? { task: { week } } : {}),
      });
      reset();
      onCreated({ codes: r.tickets.map((x) => x.code), emailQueued: r.emailQueued });
    } catch (e) {
      setError(e instanceof Error ? e.message : "The ticket could not be created");
    } finally {
      setBusy(false);
    }
  };

  const err = (k: keyof typeof problems) => touched && problems[k] && <p className="text-xs text-critical-text">{problems[k]}</p>;
  const loadingPeople = !!circle && !here && !dir.error;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (busy) return;
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent className="top-[4vh] max-h-[92vh] max-w-3xl overflow-y-auto">
        <form
          className="space-y-4 p-6"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div>
            <DialogTitle className="text-lg font-bold">Generate Ticket</DialogTitle>
            <DialogDescription className="mt-1 text-sm text-muted-foreground">
              Choose the circle, then the people to send the ticket to. Anyone with a dashboard account sees it in User Tickets; e-mail is optional.
            </DialogDescription>
          </div>

          {/* ---------------- 1. Circle ---------------- */}
          {dir.error && !d ? (
            <ErrorState error={dir.error} onRetry={dir.reload} className="py-4" />
          ) : (
            <div className="space-y-1">
              <SearchableSelect
                label="Circle / State *"
                value={circle}
                onChange={(v) => {
                  setCircle(v);
                  setPicked([]); // people belong to one circle
                }}
                options={circleOptions}
                placeholder={d ? "Select a circle" : "Loading circles…"}
                disabled={!d || busy}
              />
              {err("circle")}
              {here && here.source === "master" && (
                <p className="text-[0.75rem] text-warning-text">No Escalation Matrix is uploaded – SME and COH are not available; Area Managers come from the master data.</p>
              )}
            </div>
          )}

          {/* ---------------- 2–4. Recipients (each optional, several allowed) ---------------- */}
          <div className="space-y-2">
            <p className="text-[0.8125rem] font-semibold">
              Recipients <span className="font-normal text-muted-foreground">– any combination; each role is optional</span>
            </p>
            {(["SME", "COH", "AM"] as Role[]).map((role) => (
              <RecipientSection
                key={`${role}:${circle ?? ""}`}
                role={role}
                people={here ? (role === "COH" ? (here.coh ?? []) : role === "SME" ? here.sme : here.am) : []}
                ready={!!here}
                loading={loadingPeople}
                circleChosen={!!circle}
                picked={picked}
                accounts={accounts}
                disabled={busy}
                showCounts={taskOn}
                weekLabel={weekLabel}
                noAm={role === "AM" ? noAm : null}
                owner={owner?.name}
                onAdd={add}
                onRemove={remove}
              />
            ))}
            <FeSection
              key={`FE:${circle ?? ""}`}
              fes={here?.fe ?? []}
              selectedAms={[...amNames]}
              owner={owner?.name}
              ready={!!here}
              loading={loadingPeople}
              circleChosen={!!circle}
              picked={picked}
              accounts={accounts}
              disabled={busy}
              showCounts={taskOn}
              weekLabel={weekLabel}
              onAdd={add}
              onRemove={remove}
            />
            <ManualSection picked={picked} accounts={accounts} disabled={busy} onAdd={add} onRemove={remove} />
            <div className="grid gap-2 rounded-lg border border-border px-3 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
              <SearchableSelect
                label="Other dashboard user (optional)"
                value={otherUserId ? String(otherUserId) : undefined}
                onChange={(v) => setOtherUserId(v ? Number(v) : null)}
                options={userOptions}
                placeholder={users.data ? "Select a registered user" : "Loading users…"}
                disabled={!users.data || busy}
                allowClear
                clearLabel="None"
              />
              {otherUser && <span className="pb-2 text-[0.75rem] text-muted-foreground">{otherUser.email}</span>}
            </div>
            {err("recipients")}
          </div>

          {/* ---------------- 5–6. GP-wise Task Assignment + week ---------------- */}
          <div className="rounded-lg border border-border">
            <label className="flex cursor-pointer items-start gap-2.5 px-3 py-2.5">
              <input
                type="checkbox"
                className="mt-0.5 size-4 accent-[var(--primary)]"
                checked={taskOn}
                disabled={busy}
                onChange={(e) => {
                  setTaskOn(e.target.checked);
                  if (e.target.checked && pickedAms[0]) autofill(pickedAms[0].name);
                }}
              />
              <span>
                <span className="block text-[0.8125rem] font-semibold">GP-wise Task Assignment</span>
                <span className="block text-xs text-muted-foreground">
                  One ticket and one Excel per selected Area Manager with the week&apos;s target only – the GPs whose Planned Date falls in the selected week – and their existing achievement.
                  Each selected Field Engineer is on their Area Manager&apos;s ticket with a separate Excel of only the GPs mapped to them in the Escalation Matrix. The SME and COH selected follow each ticket: the SME reviews the GPs the Area Manager approves, the COH records the letter submission and AMC conversion.
                </span>
              </span>
            </label>
            {!taskOn && (pickedAms.length > 0 || pickedFes.length > 0) && (
              <p role="status" className="border-t border-border bg-warning-soft px-3 py-2 text-[0.78125rem] text-warning-text">
                GP-wise Task Assignment is off – the ticket and the e-mail will have no GP list, target or Excel. Tick it to send each Area Manager / Field Engineer their GPs, target and
                achievement.
              </p>
            )}
            {taskOn && (
              <div className="space-y-3 border-t border-border px-3 py-3">
                <div className="max-w-[12rem] space-y-1">
                  <span className="text-xs font-semibold text-foreground/75">Week *</span>
                  <Select ariaLabel="Week" value={week} onValueChange={setTaskWeek} options={weekOptions} className="w-full" disabled={busy} />
                </div>
                {pickedAms.length === 0 && pickedFes.length === 0 ? (
                  <p className="text-[0.78125rem] text-muted-foreground">Add one or more Area Managers or Field Engineers above – their GPs appear here.</p>
                ) : (
                  circle &&
                  week && (
                    <>
                      {pickedAms.map((a) => (
                        <AmPreview
                          key={`${a.name}:${week}:${a.typed ? "acting" : a.withNoAm ? "with" : "own"}`}
                          am={a.typed ? NO_AM : a.name}
                          title={a.typed ? `${a.name} (acting AM – GPs without an Area Manager)` : a.withNoAm ? `${a.name} + GPs without an Area Manager` : a.name}
                          withNoAm={!!a.withNoAm}
                          circle={circle}
                          week={week}
                          fes={pickedFes.filter((f) => home(f) === a.name)}
                          unmapped={(a.typed ? 0 : (amRow(a.name)?.unmappedFeGps ?? 0)) + (a.typed || a.withNoAm ? (noAm?.unmappedFeGps ?? 0) : 0)}
                        />
                      ))}
                      {feOnlyAms.map((am) => (
                        <AmPreview key={`fe-only:${am}:${week}`} am={am} circle={circle} week={week} fes={pickedFes.filter((f) => home(f) === am)} feOnly />
                      ))}
                    </>
                  )
                )}
                {noGps.length > 0 && (
                  <p role="status" className="rounded-md bg-muted/60 px-2.5 py-1.5 text-[0.75rem] text-muted-foreground">
                    {noGps.map((a) => a.name).join(", ")} {noGps.length === 1 ? "has" : "have"} no target GP (Planned Date) in {weekLabel} – the ticket is still created with 0 GPs; GPs found in the field can be added in
                    the ticket.
                  </p>
                )}
                {leftover && circle && (
                  <p role="alert" className="rounded-md border border-warning/40 bg-warning-soft px-2.5 py-1.5 text-[0.75rem] text-warning-text">
                    {circle}: {leftover.fes > 0 ? `${leftover.fes} FE${leftover.fes === 1 ? "" : "s"} (${leftover.gps} target GPs)` : `${leftover.gps} target GPs`} have no Area Manager and are not in any ticket – type an
                    acting AM, add them to an Area Manager (&quot;also take the GPs without an Area Manager&quot;), or send them FE-wise.
                  </p>
                )}
                {err("task")}
              </div>
            )}
          </div>

          {/* ---------------- 7. Optional e-mail ---------------- */}
          <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border px-3 py-2.5">
            <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={sendEmail} disabled={busy} onChange={(e) => setSendEmail(e.target.checked)} />
            <span>
              <span className="block text-[0.8125rem] font-semibold">Send Email Notification</span>
              <span className="block text-xs text-muted-foreground">
                One e-mail to each selected person only{taskOn ? "; every Area Manager gets their own GP Excel and every Field Engineer an Excel with only their GPs" : ""}. Typed addresses without a dashboard account get the e-mail only. If
                sending fails the ticket is still created and you can retry from the ticket.
              </span>
            </span>
          </label>
          {err("reach")}

          {/* ---------------- 8–10. Subject, description, priority (unchanged) ---------------- */}
          <div className="space-y-1">
            <Label htmlFor="tk-subject">
              Subject <span className="text-critical-text">*</span>
            </Label>
            <Input id="tk-subject" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={200} disabled={busy} aria-invalid={touched && !!problems.subject} placeholder="Short title of the work" />
            {err("subject")}
            {taskOn && (
              <p className="text-[0.75rem] text-muted-foreground">
                GP-wise task: each ticket gets its own subject automatically – its Area Manager (or FEs), the week with its dates and the circle, e.g. “Weekly GP task – Ashish Shringi – Week 46 (07–13 Nov) · Rajasthan”.
              </p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="tk-desc">
              Description <span className="text-critical-text">*</span>
            </Label>
            <textarea
              id="tk-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={5}
              maxLength={10000}
              disabled={busy}
              aria-invalid={touched && !!problems.description}
              placeholder="What has to be done, where, and what should be submitted"
              className={TEXTAREA}
            />
            {err("description")}
          </div>
          <div className="space-y-1">
            <span className="text-[0.8125rem] font-medium">
              Priority <span className="text-critical-text">*</span>
            </span>
            <Select ariaLabel="Priority" value={priority || undefined} onValueChange={(v) => setPriority(v as TicketPriority)} options={PRIORITIES} placeholder="Choose a priority" className="w-full sm:w-60" disabled={busy} />
            {err("priority")}
          </div>
          {error && (
            <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
              {error}
            </p>
          )}
          <div className="flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-[0.75rem] text-muted-foreground">
              {taskOn && ticketCount > 1 ? `${ticketCount} tickets will be created (one per Area Manager).` : picked.length + (otherUser ? 1 : 0) > 0 ? `${picked.length + (otherUser ? 1 : 0)} recipient${picked.length + (otherUser ? 1 : 0) === 1 ? "" : "s"} selected.` : ""}
            </p>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  reset();
                  onOpenChange(false);
                }}
              >
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={busy}>
                {busy && <Loader2 className="animate-spin" />} Generate Ticket
              </Button>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** One role (SME / COH / Area Manager): pick a name of the circle, its e-mail (or type one), add; several allowed.
 * Nobody in the matrix (or not this person): type the name and e-mail – the person works in that role. A typed Area
 * Manager on a GP-wise task is the ACTING AM of the circle's GPs without an Area Manager (with their FEs). */
function RecipientSection({
  role,
  people,
  ready,
  loading,
  circleChosen,
  picked,
  accounts,
  disabled,
  showCounts,
  weekLabel,
  noAm,
  owner,
  onAdd,
  onRemove,
}: {
  role: Role;
  people: DirectoryPerson[];
  ready: boolean;
  loading: boolean;
  circleChosen: boolean;
  picked: Picked[];
  accounts: Map<string, TicketAssignee>;
  disabled: boolean;
  showCounts: boolean;
  weekLabel?: string;
  /** AM section: the circle's GPs without an Area Manager (null = none) */
  noAm: NonNullable<TicketDirectory["noAm"]> | null;
  /** the Area Manager who already takes the GPs without an AM */
  owner?: string;
  onAdd: (p: Picked) => void;
  onRemove: (email: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [name, setName] = useState<string | undefined>(undefined);
  const [choice, setChoice] = useState<string | undefined>(undefined);
  const [manual, setManual] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [typing, setTyping] = useState(false);
  const [typedName, setTypedName] = useState("");
  const [typedMail, setTypedMail] = useState("");
  const [withNoAm, setWithNoAm] = useState(false);
  const typedMode = typing || (ready && people.length === 0);
  const actingRole = role === "AM" && showCounts; // a typed AM on a GP-wise task = acting AM of the GPs without an AM
  const actingBlocked = actingRole ? (!noAm ? "Every GP of this circle has an Area Manager in the Escalation Matrix – select one from the list (another e-mail: “Other – type an e-mail”)." : owner ? `${owner} already takes the GPs without an Area Manager.` : null) : null;
  const mine = picked.filter((p) => p.role === role);
  const person = people.find((p) => p.name === name);
  const options = useMemo(
    () =>
      people.map((p) => ({
        value: p.name,
        label: p.name,
        hint:
          role === "AM" && showCounts
            ? `${p.weekGps ?? 0} target GPs ${weekLabel ?? ""}`
            : `${p.gps.toLocaleString("en-IN")} GPs${p.emails.some((e) => e.user) ? " · has account" : ""}`,
      })),
    [people, role, showCounts, weekLabel],
  );
  const emailOptions = [...(person?.emails ?? []).map((e) => ({ value: e.email, label: `${e.email}${e.user ? " (account)" : ""}` })), { value: OTHER, label: "Other – type an e-mail" }];
  const email = (choice === OTHER ? manual : (choice ?? "")).trim().toLowerCase();

  const addNow = () => {
    if (!name) return setProblem(`Select the ${ROLE_TITLE[role]}`);
    if (!EMAIL_RE.test(email)) return setProblem("Enter a valid e-mail address");
    if (picked.some((p) => p.email === email)) return setProblem(`${email} is already selected`);
    const fromDb = person?.emails.find((e) => e.email === email)?.user;
    const acc = fromDb ? { id: fromDb.id, name: fromDb.name } : accounts.get(email) ? { id: accounts.get(email)!.id, name: accounts.get(email)!.name } : null;
    onAdd({ role, name, email, account: acc, ...(role === "AM" && withNoAm && noAm && !owner ? { withNoAm: true } : {}) });
    setName(undefined);
    setChoice(undefined);
    setManual("");
    setWithNoAm(false);
    setProblem(null);
  };
  const addTyped = () => {
    const who = typedName.trim().replace(/\s+/g, " ");
    const mail = typedMail.trim().toLowerCase();
    if (!who) return setProblem(`Type the ${ROLE_TITLE[role]}'s name`);
    if (role === "AM" && people.some((p) => p.name.toLowerCase() === who.toLowerCase())) return setProblem(`${who} is in the list – select them there`);
    if (!EMAIL_RE.test(mail)) return setProblem("Enter a valid e-mail address");
    if (picked.some((p) => p.email === mail)) return setProblem(`${mail} is already selected`);
    if (actingBlocked) return setProblem(actingBlocked);
    const acc = accounts.get(mail);
    onAdd({ role, name: who, email: mail, account: acc ? { id: acc.id, name: acc.name } : null, typed: true });
    setTypedName("");
    setTypedMail("");
    setProblem(null);
  };

  return (
    <div className="rounded-lg border border-border">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left">
        <span className="text-[0.8125rem] font-semibold">
          {ROLE_TITLE[role]} <span className="font-normal text-muted-foreground">(optional)</span>
          {mine.length > 0 && <span className="ml-2 rounded-full bg-primary-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-primary">{mine.length} selected</span>}
        </span>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div className="space-y-2 border-t border-border px-3 py-2.5">
          {!circleChosen ? (
            <p className="text-[0.78125rem] text-muted-foreground">Select the circle first.</p>
          ) : typedMode ? (
            <div className="space-y-1.5">
              <p className="text-[0.75rem] text-muted-foreground">
                {ready && people.length === 0 ? `No ${ROLE_TITLE[role]} is recorded for this circle in the database – type the name and e-mail.` : `Type a ${ROLE_TITLE[role]} who is not in the list.`}{" "}
                {actingRole
                  ? noAm
                    ? `Acting Area Manager: gets the ${noAm.weekGps} target GP${noAm.weekGps === 1 ? "" : "s"} of ${weekLabel ?? "the week"} without an Area Manager in this circle and their Field Engineers.`
                    : ""
                  : `Works on the ticket as ${ROLE_TITLE[role]}.`}
              </p>
              {actingBlocked && <p className="text-[0.75rem] text-warning-text">{actingBlocked}</p>}
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
                <div className="min-w-0 space-y-1">
                  <span className="text-xs font-semibold text-foreground/75">{ROLE_TITLE[role]} Name</span>
                  <Input value={typedName} onChange={(e) => setTypedName(e.target.value)} placeholder="Full name" maxLength={160} disabled={disabled} aria-label={`${ROLE_TITLE[role]} name (typed)`} />
                </div>
                <div className="min-w-0 space-y-1">
                  <span className="text-xs font-semibold text-foreground/75">{ROLE_TITLE[role]} Email ID</span>
                  <Input
                    type="email"
                    value={typedMail}
                    onChange={(e) => {
                      setTypedMail(e.target.value);
                      setProblem(null);
                    }}
                    placeholder="name@example.com"
                    maxLength={254}
                    disabled={disabled}
                    aria-label={`${ROLE_TITLE[role]} e-mail (typed)`}
                  />
                </div>
                <Button type="button" variant="outline" onClick={addTyped} disabled={disabled || !typedMail.trim() || !!actingBlocked}>
                  <Plus /> Add
                </Button>
              </div>
              {EMAIL_RE.test(typedMail.trim().toLowerCase()) && (
                <p className="text-[0.71875rem] text-muted-foreground">
                  {accounts.get(typedMail.trim().toLowerCase()) ? `Dashboard account found: ${accounts.get(typedMail.trim().toLowerCase())!.name}.` : "No dashboard account with this e-mail – e-mail only (turn on Send Email Notification)."}
                </p>
              )}
              {people.length > 0 && (
                <button type="button" className="text-[0.75rem] font-medium text-primary hover:underline" onClick={() => setTyping(false)}>
                  Choose from the list instead
                </button>
              )}
            </div>
          ) : (
            <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
              <SearchableSelect
                label={`${ROLE_TITLE[role]} Name`}
                value={name}
                onChange={(v) => {
                  setName(v);
                  const p = people.find((x) => x.name === v);
                  setChoice(p?.emails[0]?.email ?? OTHER);
                  setProblem(null);
                }}
                options={options}
                placeholder={loading ? "Loading…" : `Select a ${ROLE_TITLE[role]}`}
                disabled={disabled || !ready}
              />
              <div className="min-w-0 space-y-1">
                <span className="text-xs font-semibold text-foreground/75">{ROLE_TITLE[role]} Email ID</span>
                {choice === OTHER ? (
                  <div className="flex gap-1">
                    <Input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="name@example.com" maxLength={254} disabled={disabled || !name} aria-label={`${ROLE_TITLE[role]} e-mail`} />
                    {(person?.emails.length ?? 0) > 0 && (
                      <Button type="button" variant="ghost" size="sm" className="h-9 px-2" onClick={() => setChoice(person!.emails[0].email)} title="Choose a registered e-mail">
                        <X />
                      </Button>
                    )}
                  </div>
                ) : (
                  <Select ariaLabel={`${ROLE_TITLE[role]} e-mail`} value={choice} onValueChange={(v) => v && setChoice(v)} options={emailOptions} placeholder="Select the name first" className="w-full" disabled={disabled || !name} />
                )}
              </div>
              <Button type="button" variant="outline" onClick={addNow} disabled={disabled || !name}>
                <Plus /> Add
              </Button>
              {role === "AM" && showCounts && noAm && !owner && name && (
                <label className="flex cursor-pointer items-start gap-2 text-[0.75rem] sm:col-span-3">
                  <input type="checkbox" className="mt-0.5 size-3.5 accent-[var(--primary)]" checked={withNoAm} onChange={(e) => setWithNoAm(e.target.checked)} disabled={disabled} />
                  <span>
                    Also give {name} the {noAm.gps.toLocaleString("en-IN")} GPs of this circle without an Area Manager ({noAm.weekGps} target GP{noAm.weekGps === 1 ? "" : "s"} in {weekLabel}) and their Field
                    Engineers
                  </span>
                </label>
              )}
              <button type="button" className="text-left text-[0.75rem] font-medium text-primary hover:underline sm:col-span-3" onClick={() => setTyping(true)}>
                Not in the list? Type the name and e-mail
              </button>
            </div>
          )}
          {problem && <p className="text-xs text-critical-text">{problem}</p>}
          {mine.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              {mine.map((p) => (
                <li key={p.email} className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 py-1 pl-2.5 pr-1 text-[0.78125rem]">
                  <span className="font-semibold">{p.name}</span>
                  <span className="text-muted-foreground">{p.email}</span>
                  {p.typed && <span className="rounded bg-primary-soft px-1.5 py-0.5 text-[0.65625rem] font-semibold text-primary">{role === "AM" && showCounts ? "acting AM · typed" : "typed"}</span>}
                  {p.withNoAm && showCounts && <span className="rounded bg-primary-soft px-1.5 py-0.5 text-[0.65625rem] font-semibold text-primary">+ GPs without AM</span>}
                  <span className={cn("rounded px-1.5 py-0.5 text-[0.65625rem] font-semibold", p.account ? "bg-good-soft text-good-text" : "bg-warning-soft text-warning-text")}>
                    {p.account ? "Dashboard" : "E-mail only"}
                  </span>
                  <button type="button" onClick={() => onRemove(p.email)} disabled={disabled} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={`Remove ${p.name}`}>
                    <X className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Anyone else (optional, several): name and e-mail typed by hand – not from the database. A dashboard account with
 * the same e-mail sees the ticket in User Tickets; otherwise the person gets the e-mail only. View only on GP tasks. */
function ManualSection({
  picked,
  accounts,
  disabled,
  onAdd,
  onRemove,
}: {
  picked: Picked[];
  accounts: Map<string, TicketAssignee>;
  disabled: boolean;
  onAdd: (p: Picked) => void;
  onRemove: (email: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [name, setName] = useState("");
  const [mail, setMail] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const mine = picked.filter((p) => p.role === "OTHER");
  const email = mail.trim().toLowerCase();
  const account = accounts.get(email);

  const addNow = () => {
    if (!EMAIL_RE.test(email)) return setProblem("Enter a valid e-mail address");
    if (picked.some((p) => p.email === email)) return setProblem(`${email} is already selected`);
    const who = name.trim().replace(/\s+/g, " ") || account?.name || email.split("@")[0];
    onAdd({ role: "OTHER", name: who, email, account: account ? { id: account.id, name: account.name } : null });
    setName("");
    setMail("");
    setProblem(null);
  };

  return (
    <div className="rounded-lg border border-border">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left">
        <span className="text-[0.8125rem] font-semibold">
          Enter e-mail manually <span className="font-normal text-muted-foreground">(optional)</span>
          {mine.length > 0 && <span className="ml-2 rounded-full bg-primary-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-primary">{mine.length} added</span>}
        </span>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div className="space-y-2 border-t border-border px-3 py-2.5">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
            <div className="min-w-0 space-y-1">
              <span className="text-xs font-semibold text-foreground/75">Name</span>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Recipient name" maxLength={160} disabled={disabled} aria-label="Recipient name" />
            </div>
            <div className="min-w-0 space-y-1">
              <span className="text-xs font-semibold text-foreground/75">Email ID *</span>
              <Input
                type="email"
                value={mail}
                onChange={(e) => {
                  setMail(e.target.value);
                  setProblem(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addNow();
                  }
                }}
                placeholder="name@example.com"
                maxLength={254}
                disabled={disabled}
                aria-label="Recipient e-mail"
              />
            </div>
            <Button type="button" variant="outline" onClick={addNow} disabled={disabled || !email}>
              <Plus /> Add
            </Button>
          </div>
          {EMAIL_RE.test(email) && (
            <p className="text-[0.71875rem] text-muted-foreground">
              {account ? `Dashboard account found: ${account.name} – sees the ticket in User Tickets.` : "No dashboard account with this e-mail – gets the ticket by e-mail only (turn on Send Email Notification)."}
            </p>
          )}
          {problem && <p className="text-xs text-critical-text">{problem}</p>}
          {mine.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              {mine.map((p) => (
                <li key={p.email} className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 py-1 pl-2.5 pr-1 text-[0.78125rem]">
                  <span className="font-semibold">{p.name}</span>
                  <span className="text-muted-foreground">{p.email}</span>
                  <span className={cn("rounded px-1.5 py-0.5 text-[0.65625rem] font-semibold", p.account ? "bg-good-soft text-good-text" : "bg-warning-soft text-warning-text")}>
                    {p.account ? "Dashboard" : "E-mail only"}
                  </span>
                  <button type="button" onClick={() => onRemove(p.email)} disabled={disabled} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={`Remove ${p.name}`}>
                    <X className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

const ownsRow = (f: Picked) => (r: TaskPreviewRow) => !!r.feName && feKey({ name: r.feName, mappedEmail: r.feEmail ?? null }) === feKey(f);

/**
 * Field Engineer (optional, several): only the FEs mapped under the selected Area Manager(s) in the Escalation Matrix
 * (every FE of the circle while no Area Manager is selected). The e-mail comes from the matrix; another one can be typed.
 * One FE name can have rows with different FE e-mails – each is its own GP set, so the e-mail choice says how many GPs.
 * FEs of GPs without an Area Manager are always listed ("No Area Manager"): on the ticket of the AM who takes those
 * GPs, else FE-wise. An FE not in the matrix can be typed for a selected Area Manager (gets their GPs without an FE).
 */
function FeSection({
  fes,
  selectedAms,
  owner,
  ready,
  loading,
  circleChosen,
  picked,
  accounts,
  disabled,
  showCounts,
  weekLabel,
  onAdd,
  onRemove,
}: {
  fes: DirectoryFe[];
  selectedAms: string[];
  /** the Area Manager who takes the circle's GPs without an AM (their FEs go on that ticket) */
  owner?: string;
  ready: boolean;
  loading: boolean;
  circleChosen: boolean;
  picked: Picked[];
  accounts: Map<string, TicketAssignee>;
  disabled: boolean;
  showCounts: boolean;
  weekLabel?: string;
  onAdd: (p: Picked) => void;
  onRemove: (email: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [person, setPerson] = useState<string | undefined>(undefined); // "am||name"
  const [choice, setChoice] = useState<string | undefined>(undefined); // "slotIndex::email" or "slotIndex::__other"
  const [manual, setManual] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [typing, setTyping] = useState(false);
  const [typedName, setTypedName] = useState("");
  const [typedMail, setTypedMail] = useState("");
  const [typedAm, setTypedAm] = useState<string | undefined>(undefined);
  const mine = picked.filter((p) => p.role === "FE");
  // FEs of the selected Area Managers – and always the FEs of GPs without an Area Manager (never hidden)
  const available = selectedAms.length ? fes.filter((f) => selectedAms.includes(f.am) || f.am === NO_AM) : fes;
  const count = (f: DirectoryFe) => (showCounts ? `${f.weekGps} target GPs ${weekLabel ?? ""}` : `${f.gps.toLocaleString("en-IN")} GPs`);
  const amText = (am?: string) => (am === NO_AM ? (owner ? `no AM → ${owner}'s ticket` : "no Area Manager") : `AM ${am}`);
  const typedMode = typing || (ready && available.length === 0);
  const addTyped = () => {
    const who = typedName.trim().replace(/\s+/g, " ");
    const mail = typedMail.trim().toLowerCase();
    if (!who) return setProblem("Type the Field Engineer's name");
    if (!typedAm) return setProblem("Choose the Area Manager this FE works for");
    if (!EMAIL_RE.test(mail)) return setProblem("Enter a valid e-mail address");
    if (picked.some((p) => p.email === mail)) return setProblem(`${mail} is already selected`);
    if (mine.some((p) => p.typed && p.am === typedAm)) return setProblem(`One typed Field Engineer per Area Manager (${typedAm})`);
    const acc = accounts.get(mail);
    onAdd({ role: "FE", name: who, email: mail, account: acc ? { id: acc.id, name: acc.name } : null, am: typedAm, mapped: mail, typed: true });
    setTypedName("");
    setTypedMail("");
    setProblem(null);
  };
  const people = (() => {
    const m = new Map<string, { value: string; label: string; hint: string; slots: DirectoryFe[] }>();
    for (const f of available) {
      const v = `${f.am}||${f.name}`;
      const cur = m.get(v) ?? { value: v, label: f.name, hint: "", slots: [] };
      cur.slots.push(f);
      m.set(v, cur);
    }
    return [...m.values()].map((p) => ({ ...p, hint: `${amText(p.slots[0].am)} · ${p.slots.map(count).join(" + ")}` }));
  })();
  const sel = people.find((p) => p.value === person);
  const slots = sel?.slots ?? [];
  const emailOptions = slots.flatMap((f, i) => [
    ...f.emails.map((e) => ({ value: `${i}::${e.email}`, label: `${e.email}${e.user ? " (account)" : ""}${slots.length > 1 ? ` · ${count(f)}` : ""}` })),
    {
      value: `${i}::${OTHER}`,
      label: f.emails.length
        ? slots.length > 1
          ? `Other e-mail for the GPs of ${f.mappedEmail}`
          : "Other – type an e-mail"
        : `No FE e-mail in the matrix – type one${slots.length > 1 ? ` · ${count(f)}` : ""}`,
    },
  ]);
  const [slotIdx, picked1] = (choice ?? "").split("::");
  const slot = slots[Number(slotIdx)];
  const email = (picked1 === OTHER ? manual : (picked1 ?? "")).trim().toLowerCase();

  const addNow = () => {
    if (!sel || !slot) return setProblem("Select the Field Engineer");
    if (!EMAIL_RE.test(email)) return setProblem("Enter a valid e-mail address");
    if (picked.some((p) => p.email === email)) return setProblem(`${email} is already selected`);
    if (mine.some((p) => p.am === slot.am && feKey(p) === feKey(slot))) return setProblem(`${slot.name} is already selected`);
    const fromDb = slot.emails.find((e) => e.email === email)?.user;
    const acc = fromDb ? { id: fromDb.id, name: fromDb.name } : accounts.get(email) ? { id: accounts.get(email)!.id, name: accounts.get(email)!.name } : null;
    onAdd({ role: "FE", name: slot.name, email, account: acc, am: slot.am, mapped: slot.mappedEmail });
    setPerson(undefined);
    setChoice(undefined);
    setManual("");
    setProblem(null);
  };

  return (
    <div className="rounded-lg border border-border">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left">
        <span className="text-[0.8125rem] font-semibold">
          FE (Field Engineer) <span className="font-normal text-muted-foreground">(optional)</span>
          {mine.length > 0 && <span className="ml-2 rounded-full bg-primary-soft px-2 py-0.5 text-[0.6875rem] font-semibold text-primary">{mine.length} selected</span>}
        </span>
        <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <div className="space-y-2 border-t border-border px-3 py-2.5">
          {!circleChosen ? (
            <p className="text-[0.78125rem] text-muted-foreground">Select the circle first.</p>
          ) : typedMode ? (
            <div className="space-y-1.5">
              <p className="text-[0.75rem] text-muted-foreground">
                {ready && available.length === 0
                  ? selectedAms.length
                    ? `No Field Engineer is mapped under ${selectedAms.join(", ")} in the Escalation Matrix – type one.`
                    : "No Field Engineer is recorded for this circle in the Escalation Matrix – type one."
                  : "Type a Field Engineer who is not in the list."}{" "}
                The FE gets the GPs of the chosen Area Manager&apos;s ticket that have no FE in the Escalation Matrix (one typed FE per Area Manager).
              </p>
              {selectedAms.length === 0 ? (
                <p className="text-[0.75rem] text-warning-text">Add the Area Manager first (above) – a typed FE works on an Area Manager&apos;s ticket.</p>
              ) : (
                <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
                  <div className="min-w-0 space-y-1">
                    <span className="text-xs font-semibold text-foreground/75">FE Name</span>
                    <Input value={typedName} onChange={(e) => setTypedName(e.target.value)} placeholder="Full name" maxLength={160} disabled={disabled} aria-label="Field Engineer name (typed)" />
                  </div>
                  <div className="min-w-0 space-y-1">
                    <span className="text-xs font-semibold text-foreground/75">FE Email ID</span>
                    <Input type="email" value={typedMail} onChange={(e) => setTypedMail(e.target.value)} placeholder="name@example.com" maxLength={254} disabled={disabled} aria-label="Field Engineer e-mail (typed)" />
                  </div>
                  <div className="min-w-0 space-y-1">
                    <span className="text-xs font-semibold text-foreground/75">Area Manager</span>
                    <Select ariaLabel="Area Manager of the typed FE" value={typedAm} onValueChange={(v) => v && setTypedAm(v)} options={selectedAms.map((a) => ({ value: a, label: a }))} placeholder="Choose" className="w-full" disabled={disabled} />
                  </div>
                  <Button type="button" variant="outline" onClick={addTyped} disabled={disabled || !typedMail.trim()}>
                    <Plus /> Add
                  </Button>
                </div>
              )}
              {available.length > 0 && (
                <button type="button" className="text-[0.75rem] font-medium text-primary hover:underline" onClick={() => setTyping(false)}>
                  Choose from the list instead
                </button>
              )}
            </div>
          ) : (
            <>
              <p className="text-[0.75rem] text-muted-foreground">
                {selectedAms.length ? `Field Engineers of ${selectedAms.join(", ")} (and of the GPs without an Area Manager).` : "Every Field Engineer of the circle – select an Area Manager to see only theirs."} Each FE gets only the
                GPs mapped to them.
              </p>
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
                <SearchableSelect
                  label="FE Name"
                  value={person}
                  onChange={(v) => {
                    setPerson(v);
                    const p = people.find((x) => x.value === v);
                    const first = p?.slots.findIndex((f) => f.emails.length > 0) ?? -1;
                    setChoice(p ? (first >= 0 ? `${first}::${p.slots[first].emails[0].email}` : `0::${OTHER}`) : undefined);
                    setManual("");
                    setProblem(null);
                  }}
                  options={people.map(({ value, label, hint }) => ({ value, label, hint }))}
                  placeholder={loading ? "Loading…" : "Select a Field Engineer"}
                  disabled={disabled || !ready}
                />
                <div className="min-w-0 space-y-1">
                  {picked1 === OTHER && <span className="text-xs font-semibold text-foreground/75">FE Email ID</span>}
                  {picked1 === OTHER ? (
                    <div className="flex gap-1">
                      <Input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="name@example.com" maxLength={254} disabled={disabled || !sel} aria-label="Field Engineer e-mail" />
                      {emailOptions.length > 1 && (
                        <Button type="button" variant="ghost" size="sm" className="h-9 px-2" onClick={() => setChoice(undefined)} title="Choose another e-mail">
                          <X />
                        </Button>
                      )}
                    </div>
                  ) : (
                    <SearchableSelect label="FE Email ID" value={choice} onChange={(v) => v && setChoice(v)} options={emailOptions} placeholder="Select the FE first" disabled={disabled || !sel} />
                  )}
                </div>
                <Button type="button" variant="outline" onClick={addNow} disabled={disabled || !sel}>
                  <Plus /> Add
                </Button>
              </div>
              <button type="button" className="text-[0.75rem] font-medium text-primary hover:underline" onClick={() => setTyping(true)}>
                Not in the list? Type the FE&apos;s name and e-mail
              </button>
            </>
          )}
          {problem && <p className="text-xs text-critical-text">{problem}</p>}
          {mine.length > 0 && (
            <ul className="flex flex-wrap gap-1.5">
              {mine.map((p) => (
                <li key={p.email} className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 py-1 pl-2.5 pr-1 text-[0.78125rem]">
                  <span className="font-semibold">{p.name}</span>
                  <span className="text-muted-foreground">
                    {p.email} · {amText(p.am)}
                  </span>
                  {p.typed && <span className="rounded bg-primary-soft px-1.5 py-0.5 text-[0.65625rem] font-semibold text-primary">typed</span>}
                  <span className={cn("rounded px-1.5 py-0.5 text-[0.65625rem] font-semibold", p.account ? "bg-good-soft text-good-text" : "bg-warning-soft text-warning-text")}>
                    {p.account ? "Dashboard" : "E-mail only"}
                  </span>
                  <button type="button" onClick={() => onRemove(p.email)} disabled={disabled} className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={`Remove ${p.name}`}>
                    <X className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** GPs one Area Manager's task ticket will get (same rows the backend attaches): every GP of the AM, or – without the
 * Area Manager (`feOnly`) – only the selected FEs' GPs. Shows the AM's and every mapped FE's weekly target, Ready (Ach
 * Date), AMC converted (AMC Date) and remaining, and the GP-wise rows behind them, to check before generating. */
function AmPreview({
  am,
  title,
  withNoAm = false,
  circle,
  week,
  fes = [],
  unmapped = 0,
  feOnly = false,
}: {
  /** the GP group: an Area Manager of the matrix, or NO_AM (acting AM / FEs without an AM) */
  am: string;
  /** shown instead of `am` (the acting AM's name) */
  title?: string;
  withNoAm?: boolean;
  circle: string;
  week: string;
  fes?: Picked[];
  unmapped?: number;
  feOnly?: boolean;
}) {
  const q = useApiQuery(`task-preview:${week}:${circle}:${am}:${withNoAm ? 1 : 0}`, () => ticketApi.getTaskPreview(am, week, circle, withNoAm));
  const who = title ?? am;
  const [open, setOpen] = useState(false);
  const [only, setOnly] = useState<string>("all"); // GP rows of: all | an FE key | "none" (not mapped)
  const all = q.data?.rows ?? [];
  const rows = feOnly ? all.filter((r) => fes.some((f) => ownsRow(f)(r))) : all;
  const s = q.data?.summary;
  const picked = new Set(fes.map((f) => feKey(f)));
  const feLines = (s?.fes ?? []).filter((f) => !feOnly || picked.has(feKey({ name: f.name, mappedEmail: f.email })));
  const shown = rows.filter((r) => only === "all" || (only === "none" ? !r.feName : !!r.feName && feKey({ name: r.feName, mappedEmail: r.feEmail ?? null }) === only));
  const dmy = (iso?: string | null) => (iso ? new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: "UTC" }) : "—");
  return (
    <div className="rounded-md border border-border">
      <div className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[0.78125rem]">
        <span>
          <b>{feOnly ? `${fes.map((f) => `FE ${f.name}`).join(", ")} (${am})` : who}</b>{" "}
          {q.error ? (
            <span className="text-critical-text">· {q.error.message}</span>
          ) : !q.data ? (
            <span className="text-muted-foreground">· loading GPs…</span>
          ) : rows.length === 0 ? (
            <span className="text-warning-text">· no target GP this week – the ticket is still created (0 GPs)</span>
          ) : (
            <span className="text-muted-foreground">
              · {rows.length} GPs in the ticket (this week&apos;s target)
              {s && <> · Week {s.week.number} ({dmy(s.week.start)} – {dmy(s.week.end)})</>}
              {!feOnly && unmapped > 0 && <span className="text-warning-text"> · {unmapped} GP{unmapped === 1 ? "" : "s"} without an FE in the Escalation Matrix</span>}
            </span>
          )}
        </span>
      </div>

      {s && rows.length > 0 && (
        <div className="overflow-x-auto border-t border-border">
          <table className="w-full min-w-[45rem] text-[0.75rem]">
            <thead className="bg-muted">
              <tr className="text-[0.6875rem] font-semibold text-muted-foreground">
                <th className="px-2 py-1 text-left">Who</th>
                <th className="px-2 py-1 text-right" title="GPs whose Planned Date falls in the selected week">Weekly Target</th>
                <th className="px-2 py-1 text-right" title="Of the weekly target GPs: Ach Date filled">Ready (Ach Date)</th>
                <th className="px-2 py-1 text-right" title="Of the weekly target GPs: AMC Date filled">AMC Converted</th>
                <th className="px-2 py-1 text-right" title="Weekly Target − Ready">To be ready</th>
                <th className="px-2 py-1 text-right" title="Weekly Target − AMC Converted">To convert</th>
                <th className="px-2 py-1 text-right" title="All GPs of the ticket = the weekly target">Ticket GPs</th>
                <th className="px-2 py-1 text-right" title="Planned before the week and not converted yet – information only, NOT in the target or the ticket">Backlog (not in target)</th>
              </tr>
            </thead>
            <tbody className="tabular">
              {!feOnly && <FigureRow label={`${title ? who : `AM ${s.am.name}`} – all GPs`} f={s.am} strong />}
              {feLines.map((f) => (
                <FigureRow
                  key={`${f.name}|${f.email ?? ""}`}
                  label={`FE ${f.name}`}
                  hint={f.email ?? "no FE e-mail in the matrix"}
                  f={f}
                  badge={picked.has(feKey({ name: f.name, mappedEmail: f.email })) ? "selected" : undefined}
                />
              ))}
              {!feOnly && s.unmapped && <FigureRow label="FE not mapped (Escalation Matrix)" f={s.unmapped} warn />}
            </tbody>
          </table>
          <p className="border-t border-border px-2 py-1.5 text-[0.6875rem] text-muted-foreground">
            Ready = Ach Date filled (up to {dmy(s.readyAsOf)}) · AMC Converted = AMC Date filled (up to {dmy(s.amcAsOf)}) · each FE only the GPs mapped to them.
            {s.page && !feOnly && (
              <>
                {" "}
                AMC Conversion → area manager-wise table, Week {s.week.number}: Target {s.page.weekTarget} · GP Ready in the week {s.page.weekReady} · GP Achieved (AMC) in the week {s.page.weekConverted}
                {s.page.weekTarget !== s.am.week.gps && <span className="text-critical-text"> – target differs, please report</span>}.
              </>
            )}
          </p>
        </div>
      )}

      {rows.length > 0 && (
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between gap-2 border-t border-border px-3 py-1.5 text-left text-[0.75rem] font-medium text-primary">
          {open ? "Hide" : "Show"} the GP-wise details ({rows.length} GPs)
          <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} aria-hidden />
        </button>
      )}
      {open && rows.length > 0 && (
        <div className="border-t border-border">
          {feLines.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 px-2 py-1.5 text-[0.75rem]">
              <span className="text-muted-foreground">GPs of</span>
              <Select
                ariaLabel="GPs of"
                value={only}
                onValueChange={(v) => v && setOnly(v)}
                options={[
                  { value: "all", label: feOnly ? "All selected FEs" : `All – ${title ? who : `AM ${am}`}` },
                  ...feLines.map((f) => ({ value: feKey({ name: f.name, mappedEmail: f.email }), label: `FE ${f.name}${f.email ? ` (${f.email})` : ""}` })),
                  ...(!feOnly && s?.unmapped ? [{ value: "none", label: "FE not mapped" }] : []),
                ]}
                className="w-72"
              />
              <span className="text-muted-foreground">{shown.length} GPs</span>
            </div>
          )}
          <div className="max-h-56 overflow-auto">
            <table className="w-full min-w-[51.25rem] text-[0.75rem]">
              <thead className="sticky top-0 bg-muted">
                <tr className="text-left text-[0.6875rem] font-semibold text-muted-foreground">
                  {["GP Code", "GP Name", "Block", "FE", "Type", "Planned Date", "Ach Date (Ready)", "AMC Date", "Target", "Achieved", "Gap"].map((h) => (
                    <th key={h} className={cn("px-2 py-1", ["Target", "Achieved", "Gap"].includes(h) && "text-right")}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="tabular">
                {shown.map((r) => (
                  <tr key={r.gpCode} className="border-t border-border/60">
                    <td className="px-2 py-1 font-medium">{r.gpCode}</td>
                    <td className="px-2 py-1">{r.gpName}</td>
                    <td className="px-2 py-1 text-muted-foreground">{r.block ?? "—"}</td>
                    <td className={cn("px-2 py-1", !r.feName && "text-warning-text")}>{r.feName ?? "Not mapped"}</td>
                    <td className="px-2 py-1">{r.kind === "WEEK" ? "Week" : "Pending"}</td>
                    <td className="px-2 py-1">{dmy(r.plannedDate)}</td>
                    <td className="px-2 py-1">{dmy(r.readyDate)}</td>
                    <td className="px-2 py-1">{dmy(r.amcDate)}</td>
                    <td className="px-2 py-1 text-right">{r.target}</td>
                    <td className="px-2 py-1 text-right">{r.achieved}</td>
                    <td className="px-2 py-1 text-right">{r.gap}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/** One line of the target / achievement table: the week's target GPs (= the ticket) and the backlog (information). */
function FigureRow({ label, hint, f, strong, warn, badge }: { label: string; hint?: string; f: TaskFigures; strong?: boolean; warn?: boolean; badge?: string }) {
  const w = f.week;
  return (
    <tr className={cn("border-t border-border/60", strong && "font-semibold")}>
      <td className={cn("px-2 py-1", warn && "text-warning-text")}>
        {label}
        {hint && <span className="ml-1 font-normal text-muted-foreground">· {hint}</span>}
        {badge && <span className="ml-1.5 rounded bg-primary-soft px-1.5 py-0.5 text-[0.625rem] font-semibold text-primary">{badge}</span>}
      </td>
      <td className="px-2 py-1 text-right">{w.gps}</td>
      <td className="px-2 py-1 text-right">{w.ready}</td>
      <td className="px-2 py-1 text-right text-good-text">{w.amc}</td>
      <td className={cn("px-2 py-1 text-right", w.toReady > 0 ? "text-critical-text" : "text-good-text")}>{w.toReady}</td>
      <td className={cn("px-2 py-1 text-right", w.toConvert > 0 ? "text-critical-text" : "text-good-text")}>{w.toConvert}</td>
      <td className="px-2 py-1 text-right">{f.total.gps}</td>
      <td className="px-2 py-1 text-right text-muted-foreground" title={`Not in the target · ${f.backlog.ready} ready · ${f.backlog.amc} converted`}>
        {f.backlog.gps}
      </td>
    </tr>
  );
}
