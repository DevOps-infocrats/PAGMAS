"use client";

import { CalendarClock, CheckCircle2, Download, Eye, Loader2, MailCheck, Plug, Plus, RefreshCw, Save, Send, TriangleAlert, Users, X } from "lucide-react";
import { useState } from "react";
import { StatusBadge } from "@/components/feedback/badges";
import { ErrorState } from "@/components/feedback/states";
import { MiniKpi } from "@/components/kpi/mini-kpi";
import { Button } from "@/components/ui/button";
import { Checkbox, Switch } from "@/components/ui/controls";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { Card, Input, Label } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { adminApi, type OmAreaManager, type OmDelivery, type OmMailCircle, type OmMailConfig, type OmMailSettings } from "@/lib/api";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils/cn";

/**
 * O&M Daily Dashboard e-mail – one e-mail per circle with that circle's daily dashboard (HTML body): settings
 * (on / off, central CC, days x times, sending window, subject), circle-wise To / CC / subject / Area Managers /
 * remarks, preview, test mail, send now, delivery log. Backend: app/mail/om_service.py, /api/v1/mail/om/*.
 */

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const TONE: Record<OmDelivery["status"], "good" | "warning" | "critical" | "neutral" | "info"> = {
  SENT: "good",
  FAILED: "critical",
  UNKNOWN: "warning",
  SKIPPED: "neutral",
  SENDING: "info",
  PENDING: "info",
};
/** The previewed e-mail as a file: OM_Daily_Dashboard_<Circle>_<data date>.html (the same HTML, nothing re-built). */
function downloadHtml(p: { circle: string; html: string; dataAsOf?: string }) {
  const name = `OM_Daily_Dashboard_${p.circle.replace(/[^A-Za-z0-9]+/g, "_")}_${p.dataAsOf ?? new Date().toISOString().slice(0, 10)}.html`;
  const url = URL.createObjectURL(new Blob([p.html], { type: "text/html;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** circle id of the All Circles page (backend om_service.ALL_CIRCLES) */
const ALL = "all";

const errText = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : "Something went wrong");

function inZone(iso: string | null | undefined, tz: string) {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("en-IN", {
      timeZone: tz,
      weekday: "short",
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

/** E-mail addresses as removable chips + an input (Enter / comma / Add). */
function EmailChips({ value, onChange, placeholder, disabled }: { value: string[]; onChange: (v: string[]) => void; placeholder: string; disabled?: boolean }) {
  const [text, setText] = useState("");
  const [bad, setBad] = useState<string | null>(null);
  const add = () => {
    const parts = text
      .split(/[,;\s]+/)
      .map((x) => x.trim().toLowerCase())
      .filter(Boolean);
    const wrong = parts.find((p) => !EMAIL_RE.test(p));
    if (wrong) return setBad(`'${wrong}' is not an e-mail address`);
    setBad(null);
    onChange([...value, ...parts.filter((p) => !value.includes(p))]);
    setText("");
  };
  return (
    <div>
      <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-2 py-1.5">
        {value.map((e) => (
          <span key={e} className="inline-flex items-center gap-1 rounded-full bg-primary-soft px-2 py-0.5 text-[0.75rem] font-medium text-primary">
            {e}
            {!disabled && (
              <button type="button" aria-label={`Remove ${e}`} onClick={() => onChange(value.filter((x) => x !== e))} className="rounded-full hover:bg-primary/10">
                <X className="size-3" />
              </button>
            )}
          </span>
        ))}
        <input
          className="min-w-[12rem] flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          placeholder={value.length ? "Add another…" : placeholder}
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              if (text.trim()) add();
            }
          }}
          onBlur={() => text.trim() && add()}
        />
      </div>
      {bad && <p className="mt-1 text-[0.75rem] text-critical-text">{bad}</p>}
    </div>
  );
}

export function OmDailyTab() {
  const [tick, setTick] = useState(0);
  const q = useApiQuery(`om-mail:${tick}`, () => adminApi.getOmMail());
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [previewBusy, setPreviewBusy] = useState<string | null>(null);
  const [previewErr, setPreviewErr] = useState<string | null>(null);
  const [logTick, setLogTick] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const reload = () => {
    setTick((x) => x + 1);
    setLogTick((x) => x + 1);
  };
  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} />;
  const d = q.data ?? q.staleData;
  if (!d)
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> Loading…
      </p>
    );
  const tz = d.timezone;
  /** Preview of "all" (every circle on one page – preview / download only) or of one circle. */
  const openPreview = async (id: string) => {
    setPreviewBusy(id);
    setPreviewErr(null);
    try {
      const p = await adminApi.previewOmMail(id);
      const name = id === ALL ? "All Circles" : (d.circles.find((c) => c.circleId === id)?.circleName ?? id);
      setPreview({
        circleId: id,
        circle: name,
        html: p.html,
        subject: p.subject,
        week: p.week,
        dataAsOf: p.dataAsOf,
      });
    } catch (e) {
      setPreviewErr(errText(e));
    } finally {
      setPreviewBusy(null);
    }
  };
  return (
    <div className="space-y-5">
      {!d.smtpConfigured && (
        <p className="rounded-lg bg-critical-soft px-4 py-2.5 text-sm text-critical-text">
          SMTP is not usable: {d.smtpProblems.join("; ")}. Nothing can be sent until it is set up in backend/.env.
        </p>
      )}
      {!d.tiles.switchOn && (
        <p className="rounded-lg bg-warning-soft px-4 py-2.5 text-sm text-warning-text">
          Scheduled O&amp;M daily e-mails are switched off (OM_DAILY_EMAILS_ENABLED=false in backend/.env). Everything can be prepared, previewed and tested – the schedule sends
          only once the switch is on and the API restarted.
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MiniKpi
          icon={CalendarClock}
          tone="var(--primary)"
          label="Next send"
          info="The next scheduled time (only when the daily mail is switched on)."
          value={d.tiles.nextRunAt ? inZone(d.tiles.nextRunAt, tz) : "Off"}
        />
        <MiniKpi
          icon={MailCheck}
          tone="var(--good)"
          label="Sent today"
          info="Circle e-mails delivered today (scheduled + Send now; tests not counted)."
          value={String(d.tiles.sentToday)}
          unit="e-mails"
        />
        <MiniKpi
          icon={CheckCircle2}
          tone="var(--series-1)"
          label="Sent (7 days)"
          info="Circle e-mails delivered in the last 7 days."
          value={String(d.tiles.sent7d)}
          unit="e-mails"
        />
        <MiniKpi
          icon={TriangleAlert}
          tone="var(--critical)"
          label="Failed (7 days)"
          info="Failed or unknown deliveries in the last 7 days – see the delivery log."
          value={String(d.tiles.failed7d)}
          unit="e-mails"
        />
      </div>
      <SettingsCard key={`${d.settings.updatedAt ?? "new"}:${d.settings.enabled}`} d={d} onSaved={reload} />
      <Card className="flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold text-subheading">Dashboard page – All Circles</p>
          <p className="text-[0.8125rem] text-muted-foreground">
            Every circle on one HTML page to view or download. To e-mail it, pick <b>All Circles</b> in the circles list below.
          </p>
          {previewErr && !preview && <p className="mt-1 text-[0.75rem] text-critical-text">{previewErr}</p>}
        </div>
        <Button variant="outline" size="sm" disabled={!!previewBusy} onClick={() => openPreview(ALL)}>
          {previewBusy === ALL && !preview ? <Loader2 className="animate-spin" /> : <Eye />} Preview / Download
        </Button>
      </Card>
      <CirclesSection d={d} picked={picked} setPicked={setPicked} dirty={dirty} setDirty={setDirty} onSaved={reload} onPreview={setPreview} />
      <DeliveryLog tz={tz} circles={d.allCircles ? [...d.circles, d.allCircles] : d.circles} tick={logTick} />
      <Dialog open={!!preview} onOpenChange={(o) => !o && setPreview(null)}>
        <DialogContent className="top-[3vh] max-h-[94dvh] max-w-[760px] overflow-hidden p-0">
          <div className="flex flex-wrap items-start gap-3 border-b border-border px-5 py-3">
            <div className="min-w-0 flex-1">
              <DialogTitle className="text-base font-bold">Preview – {preview?.circle}</DialogTitle>
              <DialogDescription className="text-[0.8125rem] text-muted-foreground">
                {preview?.circleId === ALL ? (
                  <>
                    All circles on one page · Subject: <b className="text-foreground">{preview?.subject}</b> · {preview?.week} · goes only to the All Circles To / CC (nothing was
                    sent).
                  </>
                ) : (
                  <>
                    Subject: <b className="text-foreground">{preview?.subject}</b> · {preview?.week} · exactly what the e-mail will show (nothing was sent).
                  </>
                )}
              </DialogDescription>
              {previewErr && preview && <p className="mt-1 text-[0.75rem] text-critical-text">{previewErr}</p>}
            </div>
            {preview && (
              <div className="flex items-center gap-2">
                <Label htmlFor="om-preview-circle" className="sr-only">
                  Circle
                </Label>
                <select
                  id="om-preview-circle"
                  className="h-8 min-w-[9rem] rounded-md border border-input bg-background px-2 text-sm font-medium"
                  value={preview.circleId}
                  disabled={!!previewBusy}
                  onChange={(e) => openPreview(e.target.value)}
                >
                  <option value={ALL}>All Circles</option>
                  {d.circles.map((c) => (
                    <option key={c.circleId} value={c.circleId}>
                      {c.circleName}
                    </option>
                  ))}
                </select>
                {previewBusy && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
                <Button variant="outline" size="sm" onClick={() => downloadHtml(preview)} title="Save this page as an .html file (opens in any browser)">
                  <Download /> Download HTML
                </Button>
              </div>
            )}
          </div>
          {preview && <iframe title="E-mail preview" sandbox="" srcDoc={preview.html} className="h-[80dvh] w-full border-0 bg-[#eef2f6]" />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SettingsCard({ d, onSaved }: { d: OmMailConfig; onSaved: () => void }) {
  const [s, setS] = useState<OmMailSettings>(d.settings);
  const [newTime, setNewTime] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"save" | "conn" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const times = (day: number) => s.schedule[String(day)] ?? [];
  const setTimes = (day: number, list: string[]) =>
    setS({
      ...s,
      schedule: { ...s.schedule, [String(day)]: [...new Set(list)].sort() },
    });
  const save = async (enabled = s.enabled) => {
    setBusy("save");
    setMsg(null);
    try {
      await adminApi.saveOmMailSettings({
        enabled,
        centralCc: s.centralCc,
        schedule: s.schedule,
        windowStart: s.windowStart,
        windowEnd: s.windowEnd,
        subjectTemplate: s.subjectTemplate,
      });
      setMsg({
        ok: true,
        text: enabled ? "Saved – the daily mail is ON. Nothing was sent now; the next send is shown above." : "Saved – the daily mail is OFF.",
      });
      onSaved();
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    } finally {
      setBusy(null);
    }
  };
  const conn = async () => {
    setBusy("conn");
    setMsg(null);
    try {
      const r = await adminApi.testOmConnection();
      setMsg({ ok: r.ok, text: r.message });
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-bold text-subheading">Daily mail settings</h2>
          <p className="text-[0.8125rem] text-muted-foreground">When the e-mails go and who is always copied. Times are in {d.timezone}.</p>
        </div>
        <label className="flex items-center gap-2 text-sm font-semibold">
          <Switch checked={s.enabled} onCheckedChange={(v) => setS({ ...s, enabled: v })} aria-label="Daily mail on / off" />
          {s.enabled ? "Daily mail ON" : "Daily mail OFF"}
        </label>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-1.5">
          <Label>Central CC (added to every circle&apos;s e-mail)</Label>
          <EmailChips value={s.centralCc} onChange={(v) => setS({ ...s, centralCc: v })} placeholder="e.g. head.office@…" />
        </div>
        <div className="space-y-1.5">
          <Label>Subject (a circle may have its own)</Label>
          <Input value={s.subjectTemplate} maxLength={200} onChange={(e) => setS({ ...s, subjectTemplate: e.target.value })} />
          <p className="text-[0.75rem] text-muted-foreground">Filled in automatically: {d.placeholders.join(" · ")}</p>
        </div>
      </div>
      <div className="space-y-2">
        <Label>Send on these days and times (at most {d.maxTimesPerDay} a day)</Label>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
          {DAYS.map((name, day) => (
            <div key={name} className={cn("rounded-lg border p-2.5", times(day).length ? "border-primary/40 bg-primary-soft/30" : "border-border")}>
              <p className="text-[0.8125rem] font-semibold">
                {name} <span className="font-normal text-muted-foreground">{times(day).length ? `${times(day).length}×` : "off"}</span>
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {times(day).map((t) => (
                  <span key={t} className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-[0.75rem]">
                    {t}
                    <button
                      type="button"
                      aria-label={`Remove ${name} ${t}`}
                      onClick={() =>
                        setTimes(
                          day,
                          times(day).filter((x) => x !== t),
                        )
                      }
                    >
                      <X className="size-3" />
                    </button>
                  </span>
                ))}
              </div>
              {times(day).length < d.maxTimesPerDay && (
                <div className="mt-1.5 flex items-center gap-1">
                  <input
                    type="time"
                    aria-label={`New time for ${name}`}
                    className="h-7 w-[5.5rem] rounded border border-input bg-background px-1 text-[0.75rem]"
                    value={newTime[day] ?? "09:00"}
                    onChange={(e) => setNewTime({ ...newTime, [day]: e.target.value })}
                  />
                  <button
                    type="button"
                    className="rounded p-1 text-primary hover:bg-primary-soft"
                    aria-label={`Add time to ${name}`}
                    onClick={() => setTimes(day, [...times(day), newTime[day] ?? "09:00"])}
                  >
                    <Plus className="size-3.5" />
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[0.8125rem]">
          <span className="text-muted-foreground">Permitted sending window</span>
          <input
            type="time"
            aria-label="Window start"
            className="h-8 rounded border border-input bg-background px-2"
            value={s.windowStart}
            onChange={(e) => setS({ ...s, windowStart: e.target.value })}
          />
          <span>–</span>
          <input
            type="time"
            aria-label="Window end"
            className="h-8 rounded border border-input bg-background px-2"
            value={s.windowEnd}
            onChange={(e) => setS({ ...s, windowEnd: e.target.value })}
          />
          <span className="text-muted-foreground">· a slot missed outside it (or 2 h late) is skipped, never sent late</span>
        </div>
      </div>
      {msg && <p className={cn("rounded-md px-3 py-2 text-[0.8125rem]", msg.ok ? "bg-good-soft text-good-text" : "bg-critical-soft text-critical-text")}>{msg.text}</p>}
      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <Button variant="primary" onClick={() => save()} disabled={!!busy}>
          {busy === "save" ? <Loader2 className="animate-spin" /> : <Save />} Save settings
        </Button>
        <Button variant="outline" onClick={conn} disabled={!!busy || !d.smtpConfigured}>
          {busy === "conn" ? <Loader2 className="animate-spin" /> : <Plug />} Test connection
        </Button>
        <span className="ml-auto text-[0.75rem] text-muted-foreground">
          {d.settings.updatedBy ? `Last saved by ${d.settings.updatedBy}` : "Not saved yet"}
          {d.settings.lastRunAt ? ` · last run ${inZone(d.settings.lastRunAt, d.timezone)} (${d.settings.lastStatus ?? "—"})` : ""}
        </span>
      </div>
    </Card>
  );
}

type PreviewData = {
  circleId: string;
  circle: string;
  html: string;
  subject: string;
  week: string;
  dataAsOf?: string;
};
type PreviewFn = (p: PreviewData) => void;

/** Circles: a summary of every circle (status, To, CC, AMs, last e-mail) and ONE editor for the circle picked
 * (dropdown or a click on its row). Leaving a circle with unsaved changes asks first. */
function CirclesSection({
  d,
  picked,
  setPicked,
  dirty,
  setDirty,
  onSaved,
  onPreview,
}: {
  d: OmMailConfig;
  picked: string | null;
  setPicked: (id: string) => void;
  dirty: boolean;
  setDirty: (v: boolean) => void;
  onSaved: () => void;
  onPreview: PreviewFn;
}) {
  if (!d.circles.length) return <Card className="p-5 text-sm text-muted-foreground">No circles – upload the master data first.</Card>;
  // the All Circles mail (management, every circle on one page) is the first entry – same editor, own To / CC
  const list = d.allCircles ? [d.allCircles, ...d.circles] : d.circles;
  const current = list.find((c) => c.circleId === picked) ?? d.circles.find((c) => c.enabled) ?? d.circles[0];
  const choose = (id: string) => {
    if (id === current.circleId) return;
    if (dirty && !window.confirm(current.circleName + " has unsaved changes – leave without saving?")) return;
    setDirty(false);
    setPicked(id);
  };
  const amsOn = (c: OmMailCircle) => c.areaManagers.filter((m) => m.enabled).length;
  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-base font-bold text-subheading">Circles</h2>
        <p className="text-[0.8125rem] text-muted-foreground">
          Each circle gets its own e-mail with only its own figures. To = circle head (and the Area Managers when included) · CC = the circle&apos;s CC + the central CC.
          <b> All Circles</b> = one e-mail with every circle for the management – only its own To / CC. Pick a row to edit it.
        </p>
      </div>
      <Card className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[44rem] text-[0.8125rem]">
            <thead className="bg-muted/60 text-left text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
              <tr>
                {["Circle", "Status", "To", "CC", "Area Managers", "Last e-mail", ""].map((h) => (
                  <th key={h} className="px-4 py-2 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {list.map((c) => {
                const on = c.circleId === current.circleId;
                return (
                  <tr key={c.circleId} onClick={() => choose(c.circleId)} className={cn("cursor-pointer border-t border-border hover:bg-accent/40", on && "bg-primary-soft/40")}>
                    <td className="px-4 py-2 font-semibold">{c.circleId === ALL ? "All Circles (management)" : c.circleName}</td>
                    <td className="px-4 py-2">
                      <StatusBadge tone={c.enabled ? "good" : "neutral"}>{c.enabled ? "Sending" : "Off"}</StatusBadge>
                    </td>
                    <td className="px-4 py-2" title={c.effective.to.join(", ")}>
                      {c.effective.to.length ? c.effective.to.length : <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-2" title={c.effective.cc.join(", ")}>
                      {c.effective.cc.length ? c.effective.cc.length : <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-2">
                      {c.areaManagers.length ? `${amsOn(c)} of ${c.areaManagers.length}${c.includeAms ? "" : " (not in To)"}` : <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {c.lastStatus ? (
                        <span className="inline-flex items-center gap-1.5">
                          <StatusBadge tone={TONE[c.lastStatus]}>{c.lastStatus}</StatusBadge>
                          {inZone(c.lastAt, d.timezone)}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-2 text-right text-[0.75rem] font-medium text-primary">{on ? "Editing" : "Edit"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor="om-circle">Circle</Label>
        <select
          id="om-circle"
          className="h-9 min-w-[12rem] rounded-md border border-input bg-background px-2 text-sm font-medium"
          value={current.circleId}
          onChange={(e) => choose(e.target.value)}
        >
          {list.map((c) => (
            <option key={c.circleId} value={c.circleId}>
              {c.circleName + (c.enabled ? " · sending" : " · off")}
            </option>
          ))}
        </select>
      </div>
      <CircleCard
        key={`${current.circleId}:${JSON.stringify(current)}:${d.settings.centralCc.join(",")}`}
        c={current}
        d={d}
        onSaved={onSaved}
        onPreview={onPreview}
        onDirty={setDirty}
      />
    </div>
  );
}

function CircleCard({ c, d, onSaved, onPreview, onDirty }: { c: OmMailCircle; d: OmMailConfig; onSaved: () => void; onPreview: PreviewFn; onDirty: (v: boolean) => void }) {
  const [f, setRaw] = useState(c);
  const strip = (x: OmMailCircle) =>
    JSON.stringify({
      ...x,
      effective: null,
      remarksUpdatedAt: null,
      remarksUpdatedBy: null,
      lastAt: null,
      lastStatus: null,
    });
  const setF = (next: OmMailCircle) => {
    setRaw(next);
    onDirty(strip(next) !== strip(c));
  };
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [am, setAm] = useState({ name: "", email: "" });
  const [confirm, setConfirm] = useState(false);
  const dirty = strip(f) !== strip(c);
  const run = async (key: string, fn: () => Promise<string | void>) => {
    setBusy(key);
    setMsg(null);
    try {
      const text = await fn();
      if (text) setMsg({ ok: true, text });
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    } finally {
      setBusy(null);
    }
  };
  const save = () =>
    run("save", async () => {
      await adminApi.saveOmMailCircle(c.circleId, {
        enabled: f.enabled,
        to: f.to,
        cc: f.cc,
        subject: f.subject,
        includeAms: f.includeAms,
        areaManagers: f.areaManagers,
        remarks: f.remarks,
      });
      onDirty(false);
      onSaved();
      return `Saved ${c.circleName}.`;
    });
  const setAms = (list: OmAreaManager[]) => setF({ ...f, areaManagers: list });
  const addAm = () => {
    if (!am.name.trim() || !EMAIL_RE.test(am.email.trim()))
      return setMsg({
        ok: false,
        text: "Area Manager: type a name and a valid e-mail",
      });
    const email = am.email.trim().toLowerCase();
    if (f.areaManagers.some((x) => x.email === email)) return setMsg({ ok: false, text: `${email} is already in the list` });
    setAms([...f.areaManagers, { name: am.name.trim(), email, source: "manual", enabled: true }]);
    setAm({ name: "", email: "" });
  };
  const isAll = c.circleId === ALL; // the management e-mail: own To / CC only (no Area Managers, no central CC, no remarks)
  const amTo = f.includeAms && !isAll ? f.areaManagers.filter((x) => x.enabled).map((x) => x.email) : [];
  const toAll = [...new Set([...f.to, ...amTo])];
  const ccAll = [...new Set([...f.cc, ...(isAll ? [] : d.settings.centralCc)])].filter((x) => !toAll.includes(x));
  const goesTo = (
    <div className="rounded-lg bg-muted/40 px-3 py-2 text-[0.75rem]">
      <p>
        <b>Will go to:</b> {toAll.length ? toAll.join(", ") : <span className="text-critical-text">nobody – add a To address</span>}
      </p>
      <p className="mt-0.5">
        <b>CC:</b> {ccAll.length ? ccAll.join(", ") : "—"}
      </p>
      {isAll && <p className="mt-0.5 text-muted-foreground">Only the To / CC here receive it – no central CC, no Area Managers. Each circle&apos;s remarks are shown in it.</p>}
    </div>
  );
  return (
    <Card className={cn("overflow-hidden p-0", f.enabled && "ring-1 ring-primary/30")}>
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-muted/40 px-5 py-3">
        <h3 className="text-[0.9375rem] font-bold text-subheading">{isAll ? "All Circles (management)" : c.circleName}</h3>
        <StatusBadge tone={c.enabled ? "good" : "neutral"}>{c.enabled ? "Sending" : "Off"}</StatusBadge>
        {dirty && <span className="text-[0.75rem] font-medium text-warning-text">Unsaved changes</span>}
        <label className="ml-auto flex items-center gap-2 text-[0.8125rem] font-semibold">
          <Switch checked={f.enabled} onCheckedChange={(v) => setF({ ...f, enabled: v })} aria-label={`${c.circleName} on / off`} />
          {isAll ? "Send the All Circles mail" : "Send to this circle"}
        </label>
      </div>
      <div className="grid grid-cols-1 gap-4 p-5 xl:grid-cols-2">
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>{isAll ? "To" : "To (circle head)"}</Label>
            <EmailChips value={f.to} onChange={(v) => setF({ ...f, to: v })} placeholder={isAll ? "e.g. management e-mail" : "circle head e-mail"} />
          </div>
          <div className="space-y-1.5">
            <Label>CC</Label>
            <EmailChips value={f.cc} onChange={(v) => setF({ ...f, cc: v })} placeholder="e.g. circle MIS e-mail" />
          </div>
          <div className="space-y-1.5">
            <Label>{isAll ? "Subject (blank = default)" : "Subject (blank = the settings' subject)"}</Label>
            <Input
              value={f.subject}
              maxLength={200}
              placeholder={isAll ? (d.allSubjectDefault ?? "O&M Daily Dashboard – All Circles – {date}") : d.settings.subjectTemplate}
              onChange={(e) => setF({ ...f, subject: e.target.value })}
            />
          </div>
          {!isAll && (
            <div className="space-y-1.5">
              <Label>Remarks &amp; open points (one per line – shown in the e-mail)</Label>
              <textarea
                className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                maxLength={4000}
                value={f.remarks}
                onChange={(e) => setF({ ...f, remarks: e.target.value })}
                placeholder="e.g. 53 GPs validation done, IE shared …"
              />
              {c.remarksUpdatedBy && (
                <p className="text-[0.75rem] text-muted-foreground">
                  Last updated by {c.remarksUpdatedBy} · {inZone(c.remarksUpdatedAt, d.timezone)}
                </p>
              )}
            </div>
          )}
        </div>
        {isAll ? (
          <div className="space-y-2">{goesTo}</div>
        ) : (
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Users className="size-4 text-primary" aria-hidden />
              <span className="text-[0.8125rem] font-semibold">Area Managers of {c.circleName}</span>
              <label className="ml-auto flex items-center gap-2 text-[0.8125rem]">
                <Switch checked={f.includeAms} onCheckedChange={(v) => setF({ ...f, includeAms: v })} aria-label="Include Area Managers" />
                Include in To
              </label>
            </div>
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-[0.8125rem]">
                <thead className="bg-muted/60 text-left text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
                  <tr>
                    <th className="w-10 px-3 py-2">On</th>
                    <th className="px-3 py-2">Name</th>
                    <th className="px-3 py-2">E-mail</th>
                    <th className="px-3 py-2">Source</th>
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody>
                  {f.areaManagers.map((m) => (
                    <tr key={m.email} className="border-t border-border">
                      <td className="px-3 py-1.5">
                        <Checkbox
                          checked={m.enabled}
                          onCheckedChange={(v) => setAms(f.areaManagers.map((x) => (x.email === m.email ? { ...x, enabled: !!v } : x)))}
                          aria-label={`Send to ${m.name}`}
                        />
                      </td>
                      <td className="px-3 py-1.5 font-medium">{m.name}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">{m.email}</td>
                      <td className="px-3 py-1.5">
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 text-[0.6875rem] font-semibold",
                            m.source === "matrix" ? "bg-primary-soft text-primary" : "bg-muted text-muted-foreground",
                          )}
                        >
                          {m.source === "matrix" ? "Escalation Matrix" : "Typed"}
                        </span>
                      </td>
                      <td className="px-2">
                        {m.source === "manual" && (
                          <button
                            type="button"
                            aria-label={`Remove ${m.name}`}
                            className="rounded p-1 hover:bg-muted"
                            onClick={() => setAms(f.areaManagers.filter((x) => x.email !== m.email))}
                          >
                            <X className="size-3.5" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                  {!f.areaManagers.length && (
                    <tr>
                      <td colSpan={5} className="px-3 py-3 text-center text-muted-foreground">
                        No Area Managers yet – load them from the Escalation Matrix or type one below.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={!!busy}
                onClick={() =>
                  run("ams", async () => {
                    const r = await adminApi.refreshOmAreaManagers(c.circleId);
                    setAms(r.areaManagers);
                    return `Loaded ${r.areaManagers.filter((x) => x.source === "matrix").length} Area Managers from the Escalation Matrix – save to keep them.`;
                  })
                }
              >
                {busy === "ams" ? <Loader2 className="animate-spin" /> : <RefreshCw />} Load from Escalation Matrix
              </Button>
              <Input className="h-8 w-36" placeholder="Name" value={am.name} onChange={(e) => setAm({ ...am, name: e.target.value })} />
              <Input
                className="h-8 w-48"
                placeholder="E-mail"
                value={am.email}
                onChange={(e) => setAm({ ...am, email: e.target.value })}
                onKeyDown={(e) => e.key === "Enter" && addAm()}
              />
              <Button size="sm" variant="outline" onClick={addAm}>
                <Plus /> Add
              </Button>
            </div>
            {goesTo}
          </div>
        )}
      </div>
      {msg && <p className={cn("mx-5 mb-3 rounded-md px-3 py-2 text-[0.8125rem]", msg.ok ? "bg-good-soft text-good-text" : "bg-critical-soft text-critical-text")}>{msg.text}</p>}
      <div className="flex flex-wrap items-center gap-2 border-t border-border px-5 py-3">
        <Button variant="primary" onClick={save} disabled={!!busy}>
          {busy === "save" ? <Loader2 className="animate-spin" /> : <Save />} Save {c.circleName}
        </Button>
        <Button
          variant="outline"
          disabled={!!busy}
          onClick={() =>
            run("preview", async () => {
              const p = await adminApi.previewOmMail(c.circleId);
              onPreview({
                circleId: c.circleId,
                circle: c.circleName,
                html: p.html,
                subject: p.subject,
                week: p.week,
                dataAsOf: p.dataAsOf,
              });
            })
          }
        >
          {busy === "preview" ? <Loader2 className="animate-spin" /> : <Eye />} Preview
        </Button>
        <Button
          variant="outline"
          disabled={!!busy || !d.smtpConfigured}
          onClick={() =>
            run("test", async () => {
              const r = await adminApi.sendOmTestMail(c.circleId);
              if (!r.ok) throw new Error(r.message ?? "Test mail failed");
              onSaved();
              return `Test mail sent to ${r.to} (only to you).`;
            })
          }
        >
          {busy === "test" ? <Loader2 className="animate-spin" /> : <MailCheck />} Send test mail to me
        </Button>
        <Button
          variant="outline"
          disabled={!!busy || !d.smtpConfigured || !c.enabled || dirty}
          onClick={() => setConfirm(true)}
          title={dirty ? "Save first" : !c.enabled ? "Switch the circle on and save first" : undefined}
        >
          <Send /> Send now
        </Button>
      </div>
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent className="max-w-md p-5">
          <DialogTitle className="text-base font-bold">Send {c.circleName}&apos;s e-mail now?</DialogTitle>
          <DialogDescription className="mt-1 text-sm text-muted-foreground">
            It goes right away to {c.effective.to.join(", ") || "—"}
            {c.effective.cc.length ? `, CC ${c.effective.cc.join(", ")}` : ""}.
          </DialogDescription>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!!busy}
              onClick={() =>
                run("send", async () => {
                  setConfirm(false);
                  const r = await adminApi.sendOmMailNow(c.circleId);
                  onSaved();
                  if (!r.ok) throw new Error(r.message ?? "Sending failed – see the delivery log");
                  return `Sent ${c.circleName}'s e-mail.`;
                })
              }
            >
              <Send /> Send now
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function DeliveryLog({ tz, circles, tick }: { tz: string; circles: OmMailCircle[]; tick: number }) {
  const [f, setF] = useState<{
    status?: string;
    circle?: string;
    kind?: string;
    q?: string;
    page: number;
  }>({ page: 1 });
  const q = useApiQuery(`om-deliveries:${tick}:${JSON.stringify(f)}`, () => adminApi.listOmDeliveries(f));
  const data = q.data ?? q.staleData;
  const name = (id: string) => circles.find((c) => c.circleId === id)?.circleName ?? id;
  const sel = (key: "status" | "circle" | "kind", opts: [string, string][], all: string) => (
    <select
      aria-label={all}
      className="h-9 rounded-md border border-input bg-background px-2 text-sm"
      value={f[key] ?? ""}
      onChange={(e) => setF({ ...f, [key]: e.target.value || undefined, page: 1 })}
    >
      <option value="">{all}</option>
      {opts.map(([v, l]) => (
        <option key={v} value={v}>
          {l}
        </option>
      ))}
    </select>
  );
  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3">
        <h2 className="mr-auto text-base font-bold text-subheading">Delivery log {data ? <span className="font-normal text-muted-foreground">({data.total})</span> : null}</h2>
        <Input className="h-9 w-56" placeholder="Search subject, To, CC" value={f.q ?? ""} onChange={(e) => setF({ ...f, q: e.target.value || undefined, page: 1 })} />
        {sel(
          "status",
          [
            ["SENT", "Sent"],
            ["FAILED", "Failed"],
            ["UNKNOWN", "Unknown"],
            ["SKIPPED", "Skipped"],
          ],
          "All statuses",
        )}
        {sel(
          "circle",
          circles.map((c) => [c.circleId, c.circleName]),
          "All circles",
        )}
        {sel(
          "kind",
          [
            ["SCHEDULED", "Scheduled"],
            ["MANUAL", "Send now"],
            ["TEST", "Test"],
          ],
          "All types",
        )}
      </div>
      {q.error ? (
        <div className="p-5">
          <ErrorState error={q.error} onRetry={q.reload} />
        </div>
      ) : !data ? (
        <p className="p-5 text-sm text-muted-foreground">Loading…</p>
      ) : !data.items.length ? (
        <p className="p-6 text-center text-sm text-muted-foreground">No e-mail sent yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] text-[0.8125rem]">
            <thead className="bg-muted/60 text-left text-[0.6875rem] uppercase tracking-wide text-muted-foreground">
              <tr>
                {["Status", "Type", "Circle", "To", "CC", "Subject", "Data as of", "When"].map((h) => (
                  <th key={h} className="px-3 py-2 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((x) => (
                <tr key={x.id} className="border-t border-border align-top">
                  <td className="px-3 py-2">
                    <StatusBadge tone={TONE[x.status]}>{x.status}</StatusBadge>
                    {x.error && <span className="mt-1 block max-w-[14rem] text-[0.6875rem] text-critical-text">{x.error}</span>}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {x.kind === "MANUAL" ? "Send now" : x.kind === "TEST" ? "Test" : "Scheduled"}
                    {x.triggeredBy && x.kind !== "SCHEDULED" ? <span className="block text-[0.6875rem]">by {x.triggeredBy}</span> : null}
                  </td>
                  <td className="px-3 py-2 font-medium">{name(x.circleId)}</td>
                  <td className="max-w-[14rem] px-3 py-2 text-[0.75rem]">{x.to.join(", ") || "—"}</td>
                  <td className="px-3 py-2 text-[0.75rem] text-muted-foreground" title={x.cc.join(", ")}>
                    {x.cc.length ? `${x.cc.length} address${x.cc.length === 1 ? "" : "es"}` : "—"}
                  </td>
                  <td className="max-w-[18rem] px-3 py-2">{x.subject}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{x.dataAsOf ?? "—"}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{inZone(x.sentAt ?? x.createdAt, tz)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > data.pageSize && (
        <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-2">
          <Button size="sm" variant="outline" disabled={f.page <= 1} onClick={() => setF({ ...f, page: f.page - 1 })}>
            Previous
          </Button>
          <Button size="sm" variant="outline" disabled={f.page * data.pageSize >= data.total} onClick={() => setF({ ...f, page: f.page + 1 })}>
            Next
          </Button>
        </div>
      )}
    </Card>
  );
}
