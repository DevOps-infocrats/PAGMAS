"use client";

import { CalendarClock, Eye, FileText, Loader2, Pencil, Plus, RotateCcw, Send, Trash2, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { StatusBadge } from "@/components/feedback/badges";
import { ErrorState, TableSkeleton } from "@/components/feedback/states";
import { SearchableSelect } from "@/components/filters/searchable-select";
import { AdminGuard } from "@/components/layout/admin-guard";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, Select } from "@/components/ui/overlays";
import { Card, Input, Label } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useSession } from "@/hooks/use-session";
import {
  IS_LIVE,
  adminApi,
  type MailAudience,
  type MailConfigBody,
  type MailConfigItem,
  type MailOptions,
  type MailPreview,
  type MailRunItem,
  type MailStatus,
  type MailTemplateItem,
} from "@/lib/api";
import { cn } from "@/lib/utils/cn";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const AUDIENCE_LABEL: Record<MailAudience, string> = { am: "Area Managers", sme: "SME", coh: "COH", users: "Dashboard users" };
const RUN_TONE: Record<MailRunItem["status"], "good" | "warning" | "critical" | "neutral" | "info"> = { SUCCESS: "good", PARTIAL: "warning", FAILED: "critical", SKIPPED: "neutral", RUNNING: "info" };
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
type Tab = "schedules" | "templates" | "runs" | "smtp";

/** Date-time in the mail timezone (send times are defined there, whatever the browser's zone). */
function inZone(iso: string | null, tz: string) {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("en-IN", { timeZone: tz, day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function MailView() {
  return (
    <AdminGuard>
      <MailContent />
    </AdminGuard>
  );
}

function MailContent() {
  const [tab, setTab] = useState<Tab>("schedules");
  const [tick, setTick] = useState(0);
  const refresh = () => setTick((n) => n + 1);
  const status = useApiQuery(IS_LIVE ? `mail-status:${tick}` : null, () => adminApi.getMailStatus());
  const options = useApiQuery(IS_LIVE ? `mail-options:${tick}` : null, () => adminApi.getMailOptions());
  const templates = useApiQuery(IS_LIVE ? `mail-templates:${tick}` : null, () => adminApi.listMailTemplates());
  const tz = status.data?.timezone ?? "Asia/Kolkata";

  if (!IS_LIVE)
    return (
      <div className="space-y-6">
        <PageHeader breadcrumbs={[{ label: "Administration" }, { label: "Mail Configuration" }]} title="Mail Configuration" />
        <Card className="p-5 text-sm text-muted-foreground">Mail configuration needs the live backend.</Card>
      </div>
    );

  const tabs: { id: Tab; label: string }[] = [
    { id: "schedules", label: "Schedules" },
    { id: "templates", label: "Templates" },
    { id: "runs", label: "Run history" },
    { id: "smtp", label: "SMTP & test mail" },
  ];

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumbs={[{ label: "Administration" }, { label: "Mail Configuration" }]}
        title="Mail Configuration"
        description={`AMC Conversion e-mails to Area Managers, SME, COH (Escalation Matrix) and dashboard users – each one individually, only for their own area. Times are in ${tz}.`}
      />
      <SwitchBanner status={status.data} />
      <div role="tablist" className="flex flex-wrap gap-1 border-b border-border">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn("-mb-px border-b-2 px-3.5 py-2 text-sm font-medium transition-colors", tab === t.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground")}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "schedules" && <SchedulesTab tz={tz} options={options.data} templates={templates.data ?? []} onChanged={refresh} />}
      {tab === "templates" && <TemplatesTab templates={templates} options={options.data} onChanged={refresh} />}
      {tab === "runs" && <RunsTab tz={tz} tick={tick} />}
      {tab === "smtp" && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <StatusCard status={status.data} error={status.error} onRetry={status.reload} />
          <TestMailCard configured={status.data?.smtp.configured ?? false} />
        </div>
      )}
    </div>
  );
}

function SwitchBanner({ status }: { status?: MailStatus }) {
  if (!status) return null;
  if (!status.smtp.configured)
    return <p className="rounded-lg bg-critical-soft px-4 py-2.5 text-sm text-critical-text">SMTP is not usable: {status.smtp.problems.join("; ")}. See the “SMTP & test mail” tab.</p>;
  if (!status.reportEmailsEnabled)
    return (
      <p className="rounded-lg bg-warning-soft px-4 py-2.5 text-sm text-warning-text">
        Scheduled e-mails are switched off (AMC_REPORT_EMAILS_ENABLED=false in backend/.env). Schedules can be prepared and previewed; nothing is sent until the switch
        is on and the API restarted.
      </p>
    );
  return (
    <p className={cn("rounded-lg px-4 py-2.5 text-sm", status.schedulerRunning ? "bg-good-soft text-good-text" : "bg-warning-soft text-warning-text")}>
      {status.schedulerRunning ? "Scheduled e-mails are on – enabled schedules are sent at their next time." : "The switch is on but the scheduler is not running – restart the API."}
    </p>
  );
}

/* ================================================================ schedules */

function SchedulesTab({ tz, options, templates, onChanged }: { tz: string; options?: MailOptions; templates: MailTemplateItem[]; onChanged: () => void }) {
  const [tick, setTick] = useState(0);
  const configs = useApiQuery(`mail-configs:${tick}`, () => adminApi.listMailConfigs());
  const [editing, setEditing] = useState<MailConfigItem | "new" | null>(null);
  const [preview, setPreview] = useState<MailConfigItem | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      setTick((n) => n + 1);
      onChanged();
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Action failed" });
    }
  };

  return (
    <Card className="p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-bold text-subheading">Schedules</h2>
          <p className="text-[13px] text-muted-foreground">Who gets which template, when. Saving or enabling a schedule never sends an e-mail – it only sets the next send time.</p>
        </div>
        <Button variant="primary" onClick={() => setEditing("new")} disabled={!options}>
          <Plus /> New schedule
        </Button>
      </div>
      {configs.error ? (
        <ErrorState error={configs.error} onRetry={configs.reload} />
      ) : !configs.data ? (
        <TableSkeleton rows={3} />
      ) : configs.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">No schedule yet. Use “New schedule”.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                {["Name", "Recipients", "Template", "When", "Next send", "Last run", "Status", ""].map((c) => (
                  <th key={c} scope="col" className="py-2 pr-3 font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {configs.data.map((c) => (
                <tr key={c.id} className="border-b border-border/60 align-top last:border-0">
                  <td className="py-2.5 pr-3 font-medium">{c.name}</td>
                  <td className="py-2.5 pr-3">
                    {c.audiences.map((a) => AUDIENCE_LABEL[a]).join(", ")}
                    <div className="text-xs text-muted-foreground">{filterSummary(c, options)}</div>
                  </td>
                  <td className="py-2.5 pr-3">{c.templateName}</td>
                  <td className="py-2.5 pr-3">
                    {c.summary}
                    <div className="text-xs text-muted-foreground">from {c.startDate}</div>
                  </td>
                  <td className="py-2.5 pr-3">{c.enabled ? inZone(c.nextRunAt, tz) : "—"}</td>
                  <td className="py-2.5 pr-3">{c.lastStatus ? <StatusBadge tone={RUN_TONE[c.lastStatus as MailRunItem["status"]] ?? "neutral"}>{c.lastStatus}</StatusBadge> : <span className="text-muted-foreground">Never</span>}</td>
                  <td className="py-2.5 pr-3">{c.enabled ? <StatusBadge tone="good">Enabled</StatusBadge> : <StatusBadge tone="neutral">Disabled</StatusBadge>}</td>
                  <td className="whitespace-nowrap py-2.5 text-right">
                    <Button size="sm" variant="outline" onClick={() => act(() => adminApi.setMailConfigEnabled(c.id, !c.enabled), `${c.name} ${c.enabled ? "disabled" : "enabled"}.`)}>
                      {c.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setPreview(c)} aria-label={`Recipients of ${c.name}`} title="Recipients and e-mail preview">
                      <Eye />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(c)} aria-label={`Edit ${c.name}`}>
                      <Pencil />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`Delete ${c.name}`}
                      onClick={() => window.confirm(`Delete the schedule “${c.name}” and its run history?`) && act(() => adminApi.deleteMailConfig(c.id), `${c.name} deleted.`)}
                    >
                      <Trash2 />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {msg && <p className={cn("mt-3 text-sm", msg.ok ? "text-good-text" : "text-critical-text")}>{msg.text}</p>}

      <Dialog open={editing != null} onOpenChange={(o) => !o && setEditing(null)}>
        {editing && options && (
          <ConfigDialog
            key={editing === "new" ? "new" : editing.id}
            config={editing === "new" ? null : editing}
            options={options}
            templates={templates}
            timezone={tz}
            onDone={(text) => {
              setEditing(null);
              setMsg({ ok: true, text });
              setTick((n) => n + 1);
              onChanged();
            }}
          />
        )}
      </Dialog>
      <Dialog open={preview != null} onOpenChange={(o) => !o && setPreview(null)}>
        {preview && <RecipientsDialog config={preview} templates={templates} />}
      </Dialog>
    </Card>
  );
}

function filterSummary(c: MailConfigItem, o?: MailOptions) {
  const parts: string[] = [];
  if (c.filterCircles.length) parts.push(c.filterCircles.map((id) => o?.filters.circles.find((x) => x.id === id)?.name ?? id).join(", "));
  if (c.filterBusinessAreas.length) parts.push(`BA: ${c.filterBusinessAreas.join(", ")}`);
  if (c.filterBlocks.length) parts.push(`${c.filterBlocks.length} block(s)`);
  if (c.filterPeople.length) parts.push(`${c.filterPeople.length} chosen person(s)`);
  if (c.audiences.includes("users") && c.userIds.length) parts.push(`${c.userIds.length} user(s)`);
  return parts.length ? parts.join(" · ") : "All states";
}

/** Checkbox list with a search box for long lists. */
function CheckList({
  items,
  selected,
  onChange,
  empty,
  height = "max-h-40",
}: {
  items: { value: string; label: string; hint?: string; warn?: boolean }[];
  selected: string[];
  onChange: (v: string[]) => void;
  empty: string;
  height?: string;
}) {
  const [q, setQ] = useState("");
  const shown = q ? items.filter((i) => `${i.label} ${i.hint ?? ""}`.toLowerCase().includes(q.toLowerCase())) : items;
  if (!items.length) return <p className="text-xs text-muted-foreground">{empty}</p>;
  return (
    <div className="rounded-lg border border-border">
      {items.length > 8 && <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" className="h-8 rounded-b-none border-0 border-b" aria-label="Search list" />}
      <div className={cn("space-y-0.5 overflow-y-auto p-1.5", height)}>
        {shown.map((i) => (
          <label key={i.value} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-sm hover:bg-accent">
            <input type="checkbox" checked={selected.includes(i.value)} onChange={(e) => onChange(e.target.checked ? [...selected, i.value] : selected.filter((x) => x !== i.value))} />
            <span>{i.label}</span>
            {i.hint && <span className={cn("ml-auto truncate text-xs", i.warn ? "text-warning-text" : "text-muted-foreground")}>{i.hint}</span>}
          </label>
        ))}
      </div>
    </div>
  );
}

function ConfigDialog({ config, options, templates, timezone, onDone }: { config: MailConfigItem | null; options: MailOptions; templates: MailTemplateItem[]; timezone: string; onDone: (msg: string) => void }) {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(new Date());
  const [f, setF] = useState<MailConfigBody>(
    config
      ? {
          name: config.name,
          templateId: config.templateId,
          audiences: config.audiences,
          filterCircles: config.filterCircles,
          filterBusinessAreas: config.filterBusinessAreas,
          filterBlocks: config.filterBlocks,
          filterPeople: config.filterPeople,
          userIds: config.userIds,
          frequency: config.frequency,
          startDate: config.startDate,
          sendTime: config.sendTime,
          weekday: config.weekday,
          monthDay: config.monthDay,
          enabled: config.enabled,
        }
      : {
          name: "AMC Conversion – Area Managers daily",
          templateId: templates.find((t) => t.key === "detailed")?.id ?? null,
          audiences: ["am"],
          filterCircles: [],
          filterBusinessAreas: [],
          filterBlocks: [],
          filterPeople: [],
          userIds: [],
          frequency: "daily",
          startDate: today,
          sendTime: "09:00",
          weekday: 0,
          monthDay: 1,
          enabled: false,
        },
  );
  const [block, setBlock] = useState<string | undefined>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof MailConfigBody>(k: K, v: MailConfigBody[K]) => setF((x) => ({ ...x, [k]: v }));
  const inCircles = (id: string) => !f.filterCircles.length || f.filterCircles.includes(id);

  const bas = options.filters.businessAreas.filter((b) => inCircles(b.circleId));
  const blocks = options.filters.blocks.filter((b) => inCircles(b.circleId));
  const people = options.people.filter((p) => f.audiences.includes(p.role) && inCircles(p.circleId));
  const valid = f.name.trim().length >= 2 && f.audiences.length > 0 && /^\d{2}:\d{2}$/.test(f.sendTime) && !!f.startDate;

  const save = async () => {
    setBusy(true);
    setError(null);
    const body: MailConfigBody = {
      ...f,
      name: f.name.trim(),
      weekday: f.frequency === "weekly" ? (f.weekday ?? 0) : null,
      monthDay: f.frequency === "monthly" ? (f.monthDay ?? 1) : null,
      filterPeople: f.filterPeople.filter((id) => people.some((p) => p.id === id)),
      userIds: f.audiences.includes("users") ? f.userIds : [],
    };
    try {
      if (config) await adminApi.updateMailConfig(config.id, body);
      else await adminApi.createMailConfig(body);
      onDone(`${body.name} saved${body.enabled ? " – it runs at the next scheduled time" : " (disabled)"}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogContent className="top-[5vh] max-h-[90vh] max-w-2xl overflow-y-auto">
      <form
        className="space-y-4 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && !busy) void save();
        }}
      >
        <div>
          <DialogTitle className="flex items-center gap-2 text-base font-bold">
            <CalendarClock className="size-4" /> {config ? "Edit schedule" : "New schedule"}
          </DialogTitle>
          <DialogDescription className="text-[13px] text-muted-foreground">Each recipient gets one e-mail with only their own GPs. Saving does not send anything.</DialogDescription>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="c-name">Name</Label>
            <Input id="c-name" value={f.name} onChange={(e) => set("name", e.target.value)} maxLength={120} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c-tpl">Template</Label>
            <Select ariaLabel="Template" className="w-full" value={f.templateId ? String(f.templateId) : ""} onValueChange={(v) => set("templateId", v ? Number(v) : null)} options={templates.map((t) => ({ value: String(t.id), label: t.name }))} placeholder="Detailed report (default)" />
          </div>
        </div>

        <Section title="1. Who receives it">
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {options.audiences.map((a) => (
              <label key={a.id} className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={f.audiences.includes(a.id)} onChange={(e) => set("audiences", e.target.checked ? [...f.audiences, a.id] : f.audiences.filter((x) => x !== a.id))} />
                {AUDIENCE_LABEL[a.id]}
              </label>
            ))}
          </div>
          {!options.hasMatrix && f.audiences.some((a) => a !== "users") && <p className="text-xs text-warning-text">No Escalation Matrix uploaded – Area Managers, SME and COH come from it.</p>}
          <p className="text-xs text-muted-foreground">Area Managers get their own GPs (block-wise). SME and COH get their circle (area-manager-wise). Dashboard users get their assigned areas.</p>
        </Section>

        <Section title="2. Which area (optional – empty = everything)">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted-foreground">States</span>
              <CheckList items={options.filters.circles.map((c) => ({ value: c.id, label: c.name }))} selected={f.filterCircles} onChange={(v) => set("filterCircles", v)} empty="No data" height="max-h-28" />
            </div>
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted-foreground">Business areas</span>
              <CheckList
                items={bas.map((b) => ({ value: b.name, label: b.name, hint: options.filters.circles.find((c) => c.id === b.circleId)?.name }))}
                selected={f.filterBusinessAreas}
                onChange={(v) => set("filterBusinessAreas", v)}
                empty="No business areas"
                height="max-h-28"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">Blocks</span>
            <div className="flex gap-2">
              <SearchableSelect className="flex-1" label="Block" hideLabel value={block} onChange={setBlock} options={blocks.map((b) => ({ value: b.id, label: b.name }))} placeholder="Add a block…" />
              <Button
                type="button"
                variant="outline"
                disabled={!block}
                onClick={() => {
                  if (block && !f.filterBlocks.includes(block)) set("filterBlocks", [...f.filterBlocks, block]);
                  setBlock(undefined);
                }}
              >
                <Plus /> Add
              </Button>
            </div>
            {f.filterBlocks.length > 0 && (
              <ul className="flex flex-wrap gap-1.5">
                {f.filterBlocks.map((id) => (
                  <li key={id} className="inline-flex items-center gap-1 rounded bg-primary-soft py-0.5 pl-2 pr-1 text-xs text-primary">
                    {options.filters.blocks.find((b) => b.id === id)?.name ?? id}
                    <button type="button" className="rounded p-0.5 hover:bg-primary/15" aria-label="Remove block" onClick={() => set("filterBlocks", f.filterBlocks.filter((x) => x !== id))}>
                      <X className="size-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {f.audiences.some((a) => a !== "users") && (
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted-foreground">Only these people (empty = everyone of the chosen roles)</span>
              <CheckList
                items={people.map((p) => ({ value: p.id, label: `${p.name} – ${p.roleLabel}, ${p.circle}`, hint: p.emails[0] ?? "no e-mail", warn: !p.emails.length }))}
                selected={f.filterPeople}
                onChange={(v) => set("filterPeople", v)}
                empty="Nobody of the chosen roles in the selected states."
              />
            </div>
          )}
          {f.audiences.includes("users") && (
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted-foreground">Dashboard users (empty = all active users)</span>
              <CheckList items={options.users.map((u) => ({ value: String(u.id), label: u.name, hint: `${u.email} · ${u.role}` }))} selected={f.userIds.map(String)} onChange={(v) => set("userIds", v.map(Number))} empty="No users" />
            </div>
          )}
        </Section>

        <Section title={`3. When (${timezone})`}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="c-freq">Frequency</Label>
              <Select
                ariaLabel="Frequency"
                className="w-full"
                value={f.frequency}
                onValueChange={(v) => set("frequency", v as MailConfigBody["frequency"])}
                options={[
                  { value: "daily", label: "Daily" },
                  { value: "weekly", label: "Weekly" },
                  { value: "monthly", label: "Monthly" },
                ]}
              />
            </div>
            {f.frequency === "weekly" && (
              <div className="space-y-1.5">
                <Label htmlFor="c-wd">Day of week</Label>
                <Select ariaLabel="Day of week" className="w-full" value={String(f.weekday ?? 0)} onValueChange={(v) => set("weekday", Number(v))} options={WEEKDAYS.map((d, i) => ({ value: String(i), label: d }))} />
              </div>
            )}
            {f.frequency === "monthly" && (
              <div className="space-y-1.5">
                <Label htmlFor="c-md">Day of month</Label>
                <Select
                  ariaLabel="Day of month"
                  className="w-full"
                  value={String(f.monthDay ?? 1)}
                  onValueChange={(v) => set("monthDay", Number(v))}
                  options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: i + 1 > 28 ? `${i + 1} (or last day)` : String(i + 1) }))}
                />
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="c-start">Start date</Label>
              <Input id="c-start" type="date" value={f.startDate} onChange={(e) => set("startDate", e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="c-time">Send time</Label>
              <Input id="c-time" type="time" value={f.sendTime} onChange={(e) => set("sendTime", e.target.value.slice(0, 5))} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={f.enabled} onChange={(e) => set("enabled", e.target.checked)} />
            Enabled (sends at the next scheduled time, when scheduled e-mails are switched on)
          </label>
        </Section>

        {error && <p className="text-sm text-critical-text">{error}</p>}
        <div className="flex justify-end">
          <Button type="submit" variant="primary" disabled={!valid || busy}>
            {busy && <Loader2 className="animate-spin" />} Save
          </Button>
        </div>
      </form>
    </DialogContent>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="space-y-2.5 rounded-lg border border-border p-3">
      <legend className="px-1 text-sm font-semibold">{title}</legend>
      {children}
    </fieldset>
  );
}

function RecipientsDialog({ config, templates }: { config: MailConfigItem; templates: MailTemplateItem[] }) {
  const q = useApiQuery(`mail-recipients:${config.id}`, () => adminApi.previewMailRecipients(config.id));
  const t = templates.find((x) => x.id === config.templateId) ?? templates.find((x) => x.key === "detailed");
  const [shown, setShown] = useState<MailPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const showEmail = async () => {
    if (!t) return;
    setLoading(true);
    setError(null);
    try {
      setShown(await adminApi.previewMailTemplate({ subject: t.subject, body: t.body, configId: config.id }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Preview failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <DialogContent className="top-[5vh] max-h-[90vh] max-w-3xl overflow-y-auto">
      <div className="space-y-3 p-5">
        <DialogTitle className="text-base font-bold">Recipients – {config.name}</DialogTitle>
        <DialogDescription className="text-[13px] text-muted-foreground">Who would receive the next e-mail and what each one covers. Nothing is sent from here.</DialogDescription>
        {q.error ? (
          <ErrorState error={q.error} onRetry={q.reload} />
        ) : !q.data ? (
          <TableSkeleton rows={4} />
        ) : !q.data.hasData ? (
          <p className="text-sm text-warning-text">No active data yet.</p>
        ) : (
          <>
            <p className="text-sm">
              <b>{q.data.recipients.length}</b> e-mail(s) · <b>{q.data.skipped.length}</b> skipped
            </p>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="py-1.5 pr-3 font-medium">Recipient</th>
                  <th className="py-1.5 pr-3 font-medium">Role</th>
                  <th className="py-1.5 pr-3 font-medium">Covers</th>
                  <th className="py-1.5 pr-3 text-right font-medium">GPs</th>
                </tr>
              </thead>
              <tbody>
                {q.data.recipients.map((r) => (
                  <tr key={r.emails[0]} className="border-b border-border/60 align-top last:border-0">
                    <td className="py-1.5 pr-3">
                      <div className="font-medium">{r.name}</div>
                      <div className="text-xs text-muted-foreground">{r.emails.join(", ")}</div>
                    </td>
                    <td className="py-1.5 pr-3 text-xs">{r.roles}</td>
                    <td className="py-1.5 pr-3 text-xs">
                      {r.areas.join("; ")}
                      <div className="text-muted-foreground">{r.breakdown === "block" ? "block-wise table" : "area-manager-wise table"}</div>
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{r.gps.toLocaleString("en-IN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {q.data.skipped.length > 0 && (
              <div>
                <h3 className="mb-1 text-sm font-semibold">Not sent to</h3>
                <ul className="space-y-0.5 text-xs text-muted-foreground">
                  {q.data.skipped.map((s, i) => (
                    <li key={i}>
                      {s.name} ({s.role}) – {s.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {q.data.recipients.length > 0 && t && (
              <div className="space-y-2 border-t border-border pt-3">
                <Button variant="outline" size="sm" onClick={showEmail} disabled={loading}>
                  {loading ? <Loader2 className="animate-spin" /> : <FileText />} Preview the first recipient’s e-mail
                </Button>
                {error && <p className="text-sm text-critical-text">{error}</p>}
                {shown && <PreviewFrame preview={shown} />}
              </div>
            )}
          </>
        )}
      </div>
    </DialogContent>
  );
}

function PreviewFrame({ preview }: { preview: MailPreview }) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs text-muted-foreground">
        To: <b>{preview.recipient.name}</b> ({preview.recipient.role}) · {preview.recipient.emails.join(", ")}
      </p>
      <p className="text-sm">
        <span className="text-muted-foreground">Subject:</span> <b>{preview.subject}</b>
      </p>
      {/* sandboxed: the preview HTML cannot run scripts or reach the page */}
      <iframe title="E-mail preview" sandbox="" srcDoc={preview.html} className="h-[420px] w-full rounded-lg border border-border bg-white" />
    </div>
  );
}

/* ================================================================ templates */

function TemplatesTab({ templates, options, onChanged }: { templates: ReturnType<typeof useApiQuery<MailTemplateItem[]>>; options?: MailOptions; onChanged: () => void }) {
  const [editing, setEditing] = useState<MailTemplateItem | "new" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      onChanged();
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Action failed" });
    }
  };

  return (
    <Card className="p-5">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-bold text-subheading">Templates</h2>
          <p className="text-[13px] text-muted-foreground">
            Text with placeholders such as {"{{recipient_name}}"} or {"{{breakdown_table}}"}, filled per recipient. Built-in templates can be edited and reset; your own
            ones can also be deleted.
          </p>
        </div>
        <Button variant="primary" onClick={() => setEditing("new")}>
          <Plus /> New template
        </Button>
      </div>
      {templates.error ? (
        <ErrorState error={templates.error} onRetry={templates.reload} />
      ) : !templates.data ? (
        <TableSkeleton rows={3} />
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          {templates.data.map((t) => (
            <div key={t.id} className="flex flex-col rounded-lg border border-border p-4">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold">{t.name}</h3>
                {t.builtIn ? <StatusBadge tone="info">Built-in</StatusBadge> : <StatusBadge tone="neutral">Custom</StatusBadge>}
              </div>
              {t.description && <p className="mt-1 text-xs text-muted-foreground">{t.description}</p>}
              <p className="mt-2 line-clamp-2 text-xs">
                <span className="text-muted-foreground">Subject:</span> {t.subject}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">Used by {t.usedBy} schedule(s)</p>
              <div className="mt-auto flex flex-wrap gap-1 pt-3">
                <Button size="sm" variant="outline" onClick={() => setEditing(t)}>
                  <Pencil /> Edit & preview
                </Button>
                {t.builtIn ? (
                  <Button size="sm" variant="ghost" onClick={() => window.confirm(`Reset “${t.name}” to its original text?`) && act(() => adminApi.resetMailTemplate(t.id), `${t.name} reset.`)}>
                    <RotateCcw /> Reset
                  </Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => window.confirm(`Delete the template “${t.name}”?`) && act(() => adminApi.deleteMailTemplate(t.id), `${t.name} deleted.`)}>
                    <Trash2 /> Delete
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      {msg && <p className={cn("mt-3 text-sm", msg.ok ? "text-good-text" : "text-critical-text")}>{msg.text}</p>}
      <Dialog open={editing != null} onOpenChange={(o) => !o && setEditing(null)}>
        {editing && options && (
          <TemplateDialog
            key={editing === "new" ? "new" : editing.id}
            template={editing === "new" ? null : editing}
            options={options}
            onDone={(text) => {
              setEditing(null);
              setMsg({ ok: true, text });
              onChanged();
            }}
          />
        )}
      </Dialog>
    </Card>
  );
}

function TemplateDialog({ template, options, onDone }: { template: MailTemplateItem | null; options: MailOptions; onDone: (msg: string) => void }) {
  const [name, setName] = useState(template?.name ?? "");
  const [description, setDescription] = useState(template?.description ?? "");
  const [subject, setSubject] = useState(template?.subject ?? "AMC Conversion – {{area}} – {{data_date}}");
  const [body, setBody] = useState(template?.body ?? "Dear {{recipient_name}},\n\n{{summary_table}}\n\nRegards,\nPratap Network Analytics");
  const [person, setPerson] = useState<string | undefined>(options.people.find((p) => p.emails.length)?.id);
  const [preview, setPreview] = useState<MailPreview | null>(null);
  const [busy, setBusy] = useState<"save" | "preview" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const peopleOptions = useMemo(() => options.people.filter((p) => p.emails.length).map((p) => ({ value: p.id, label: `${p.name} – ${p.roleLabel}, ${p.circle}` })), [options.people]);

  const insert = (ph: string, table: boolean) => {
    const el = bodyRef.current;
    const token = table ? `\n{{${ph}}}\n` : `{{${ph}}}`;
    if (!el) return setBody((b) => b + token);
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? body.length;
    setBody(body.slice(0, start) + token + body.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      el.selectionStart = el.selectionEnd = start + token.length;
    });
  };

  const run = async (kind: "save" | "preview") => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "preview") {
        setPreview(await adminApi.previewMailTemplate({ subject, body, personId: person }));
      } else {
        const payload = { name: name.trim(), description: description.trim() || null, subject: subject.trim(), body };
        if (template) await adminApi.updateMailTemplate(template.id, payload);
        else await adminApi.createMailTemplate(payload);
        onDone(`${payload.name} saved.`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <DialogContent className="top-[4vh] max-h-[92vh] max-w-5xl overflow-y-auto">
      <div className="grid grid-cols-1 gap-5 p-5 lg:grid-cols-2">
        <div className="space-y-3">
          <DialogTitle className="text-base font-bold">{template ? `Edit “${template.name}”` : "New template"}</DialogTitle>
          <DialogDescription className="text-[13px] text-muted-foreground">Click a placeholder to insert it. Tables must stand on their own line.</DialogDescription>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="t-name">Name</Label>
              <Input id="t-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="t-desc">Description</Label>
              <Input id="t-desc" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={300} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="t-subject">Subject</Label>
            <Input id="t-subject" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={300} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="t-body">Body</Label>
            <textarea
              id="t-body"
              ref={bodyRef}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={14}
              maxLength={20000}
              className="w-full rounded-md border border-input bg-card px-3 py-2 font-mono text-[13px] leading-relaxed shadow-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25"
            />
          </div>
          <div className="space-y-1">
            <span className="text-xs font-medium text-muted-foreground">Placeholders</span>
            <div className="flex flex-wrap gap-1">
              {options.placeholders.map((p) => (
                <button
                  key={p.name}
                  type="button"
                  title={p.description}
                  onClick={() => insert(p.name, p.table)}
                  className={cn("rounded px-1.5 py-0.5 font-mono text-[11px] hover:brightness-95", p.table ? "bg-good-soft text-good-text" : "bg-primary-soft text-primary")}
                >
                  {p.name}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground">Blue = text value · green = table</p>
          </div>
          {error && <p className="text-sm text-critical-text">{error}</p>}
          <div className="flex justify-end">
            <Button variant="primary" onClick={() => run("save")} disabled={busy != null || name.trim().length < 2 || !subject.trim() || !body.trim()}>
              {busy === "save" && <Loader2 className="animate-spin" />} Save template
            </Button>
          </div>
        </div>
        <div className="space-y-3 lg:border-l lg:border-border lg:pl-5">
          <h3 className="text-sm font-semibold">Preview with real data</h3>
          <div className="flex gap-2">
            <SearchableSelect className="flex-1" label="Preview for" hideLabel value={person} onChange={setPerson} options={peopleOptions} placeholder="Choose a person…" />
            <Button variant="outline" onClick={() => run("preview")} disabled={busy != null}>
              {busy === "preview" ? <Loader2 className="animate-spin" /> : <Eye />} Preview
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">Renders the e-mail exactly as this person would get it. Nothing is sent.</p>
          {preview ? <PreviewFrame preview={preview} /> : <div className="grid h-[420px] place-items-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">Preview appears here</div>}
        </div>
      </div>
    </DialogContent>
  );
}

/* ================================================================ runs, SMTP, test mail */

function RunsTab({ tz, tick }: { tz: string; tick: number }) {
  const runs = useApiQuery(`mail-runs:${tick}`, () => adminApi.listMailRuns());
  return (
    <Card className="p-5">
      <h2 className="text-[15px] font-bold text-subheading">Run history</h2>
      <p className="mb-4 text-[13px] text-muted-foreground">One row per scheduled send. A send missed for more than 6 hours (server not running) is skipped, not sent late.</p>
      {runs.error ? (
        <ErrorState error={runs.error} onRetry={runs.reload} />
      ) : !runs.data ? (
        <TableSkeleton rows={3} />
      ) : runs.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing has been sent yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                {["Schedule", "Planned for", "Status", "Sent", "Failed", "Skipped", "Note"].map((c) => (
                  <th key={c} scope="col" className="py-2 pr-3 font-medium">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.data.map((r) => (
                <tr key={r.id} className="border-b border-border/60 align-top last:border-0">
                  <td className="py-2.5 pr-3">{r.configName}</td>
                  <td className="py-2.5 pr-3">{inZone(r.scheduledFor, tz)}</td>
                  <td className="py-2.5 pr-3">
                    <StatusBadge tone={RUN_TONE[r.status]}>{r.status}</StatusBadge>
                  </td>
                  <td className="py-2.5 pr-3 tabular-nums">{r.sent}</td>
                  <td className="py-2.5 pr-3 tabular-nums">{r.failed}</td>
                  <td className="py-2.5 pr-3 tabular-nums">{r.skipped}</td>
                  <td className="max-w-[380px] py-2.5 pr-3 text-xs text-muted-foreground">{r.message ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function StatusCard({ status, error, onRetry }: { status?: MailStatus; error?: Error; onRetry: () => void }) {
  return (
    <Card className="p-5">
      <h2 className="text-[15px] font-bold text-subheading">Mail server (SMTP)</h2>
      <p className="mb-4 text-[13px] text-muted-foreground">Read from the MAIL_* settings in backend/.env. The password is never shown.</p>
      {error ? (
        <ErrorState error={error} onRetry={onRetry} />
      ) : !status ? (
        <TableSkeleton rows={3} />
      ) : (
        <dl className="space-y-2.5 text-sm">
          <Row label="SMTP">{status.smtp.configured ? <StatusBadge tone="good">Configured</StatusBadge> : <StatusBadge tone="critical">Not usable</StatusBadge>}</Row>
          {status.smtp.problems.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-critical-text">
              {status.smtp.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          <Row label="Server">{status.smtp.server ? `${status.smtp.server}:${status.smtp.port ?? "?"}` : "—"}</Row>
          <Row label="Security">{status.smtp.security === "none" ? "None (plain)" : status.smtp.security}</Row>
          <Row label="Sender">{status.smtp.sender ?? "—"}</Row>
          <Row label="Login">{status.smtp.usernameSet ? "With username / password" : "No login"}</Row>
          <Row label="Scheduled AMC e-mails">{status.reportEmailsEnabled ? <StatusBadge tone={status.schedulerRunning ? "good" : "warning"}>{status.schedulerRunning ? "On" : "On – restart the API"}</StatusBadge> : <StatusBadge tone="neutral">Off</StatusBadge>}</Row>
          <Row label="Timezone">{status.timezone}</Row>
        </dl>
      )}
    </Card>
  );
}

function TestMailCard({ configured }: { configured: boolean }) {
  const { session } = useSession();
  const [to, setTo] = useState(session?.email ?? "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const valid = EMAIL_RE.test(to.trim());

  const send = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await adminApi.sendTestMail(to.trim());
      setResult({ ok: r.ok, text: r.message });
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : "Sending failed" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5">
      <h2 className="text-[15px] font-bold text-subheading">Send Test Mail</h2>
      <p className="mb-4 text-[13px] text-muted-foreground">Sends one short test message to check the SMTP settings. No report is built and no schedule runs.</p>
      <form
        className="flex flex-col gap-2 sm:flex-row sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && !busy) void send();
        }}
      >
        <div className="flex-1 space-y-1.5">
          <Label htmlFor="test-to">Recipient</Label>
          <Input id="test-to" type="email" value={to} onChange={(e) => setTo(e.target.value)} placeholder="name@pratap.co.in" maxLength={254} />
        </div>
        <Button type="submit" variant="primary" disabled={!valid || busy || !configured}>
          {busy ? <Loader2 className="animate-spin" /> : <Send />} Send Test Mail
        </Button>
      </form>
      {!configured && <p className="mt-2 text-xs text-warning-text">Fix the SMTP settings first (left card).</p>}
      {result && <p className={cn("mt-3 text-sm", result.ok ? "text-good-text" : "text-critical-text")}>{result.text}</p>}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}
