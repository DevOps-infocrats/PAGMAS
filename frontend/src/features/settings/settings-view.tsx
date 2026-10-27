"use client";

import { Loader2, Monitor, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { AdminGuard } from "@/components/layout/admin-guard";
import { PageHeader } from "@/components/layout/page-header";
import { useMeta } from "@/components/providers/data-provider";
import { useTheme, type ThemePreference } from "@/components/providers/theme-provider";
import { Button } from "@/components/ui/button";
import { Card, Input, Label } from "@/components/ui/primitives";
import { API_MODE, IS_LIVE } from "@/lib/api";
import { changePassword } from "@/lib/auth/session";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatDate, formatDateTime } from "@/lib/utils/format";

export function SettingsView() {
  return (
    <AdminGuard>
      <SettingsContent />
    </AdminGuard>
  );
}

function SettingsContent() {
  const { preference, setPreference } = useTheme();
  const meta = useMeta();
  const themes: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Monitor },
  ];

  return (
    <div className="space-y-8">
      <PageHeader breadcrumbs={[{ label: "Administration" }, { label: "Settings" }]} title="Settings" description="Users, security and workspace preferences." />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <SettingsCard title="Data environment" description="Where the dashboard reads its data from.">
          <dl className="space-y-3 text-sm">
            <Row label="Mode">
              <span className={cn("rounded px-2 py-0.5 font-medium", IS_LIVE ? "bg-good-soft text-good-text" : "bg-warning-soft text-warning-text")}>
                {API_MODE === "mock" ? "Demo data" : "Live backend"}
              </span>
            </Row>
            {meta?.datasetFileName && <Row label="Active file">{meta.datasetFileName}</Row>}
            {meta?.dataAsOf && <Row label="Data as of">{formatDate(meta.dataAsOf)}</Row>}
            {meta?.importedAt && <Row label="Imported">{formatDateTime(meta.importedAt)}</Row>}
            <Row label="Thresholds">
              Healthy ≥ {meta?.thresholds?.healthy ?? THRESHOLDS.healthy}% · Penalty &lt; {meta?.thresholds?.penalty ?? THRESHOLDS.penalty}%
            </Row>
          </dl>
        </SettingsCard>

        <SettingsCard title="Appearance" description="Saved in this browser only.">
          <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-3">
            {themes.map((t) => (
              <button
                key={t.value}
                type="button"
                role="radio"
                aria-checked={preference === t.value}
                onClick={() => setPreference(t.value)}
                className={cn(
                  "flex flex-col items-center gap-2 rounded-lg border p-4 text-sm transition-colors hover:bg-accent",
                  preference === t.value ? "border-primary bg-primary-soft/50 font-medium" : "border-border",
                )}
              >
                <t.icon className="size-5 text-muted-foreground" />
                {t.label}
              </button>
            ))}
          </div>
        </SettingsCard>

        {IS_LIVE && <ChangePasswordCard />}
        <SettingsCard title="Users" description="Accounts, roles and e-mail areas are managed on their own page.">
          <Link href="/dashboard/users" className="text-sm font-medium text-primary hover:underline">
            Open User Management →
          </Link>
        </SettingsCard>
      </div>
    </div>
  );
}

function ChangePasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <SettingsCard title="Change your password" description="At least 12 characters with 3 of: lower-case, upper-case, digits, symbols.">
      <form
        className="space-y-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setMsg(null);
          if (next !== confirm) return setMsg({ ok: false, text: "New passwords do not match." });
          setBusy(true);
          try {
            await changePassword(current, next);
            setMsg({ ok: true, text: "Password changed. Other sessions were signed out." });
            setCurrent("");
            setNext("");
            setConfirm("");
          } catch (err) {
            setMsg({ ok: false, text: err instanceof Error ? err.message : "Could not change password" });
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field id="pw-current" label="Current password" type="password" value={current} onChange={setCurrent} autoComplete="current-password" />
        <Field id="pw-new" label="New password" type="password" value={next} onChange={setNext} autoComplete="new-password" />
        <Field id="pw-confirm" label="Repeat new password" type="password" value={confirm} onChange={setConfirm} autoComplete="new-password" />
        {msg && <p className={cn("text-sm", msg.ok ? "text-good-text" : "text-critical-text")}>{msg.text}</p>}
        <Button type="submit" variant="primary" disabled={busy || !current || !next}>
          {busy && <Loader2 className="animate-spin" />} Update password
        </Button>
      </form>
    </SettingsCard>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  autoComplete?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type={type} value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete} maxLength={128} />
    </div>
  );
}

function SettingsCard({ title, description, children, className }: { title: string; description: string; children: React.ReactNode; className?: string }) {
  return (
    <Card className={cn("p-5", className)}>
      <h2 className="text-[15px] font-bold text-subheading">{title}</h2>
      <p className="mb-4 text-[13px] text-muted-foreground">{description}</p>
      {children}
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
