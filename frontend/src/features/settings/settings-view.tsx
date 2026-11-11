"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { ChangePasswordForm, PASSWORD_RULE } from "@/components/account/change-password-form";
import { AdminGuard } from "@/components/layout/admin-guard";
import { PageHeader } from "@/components/layout/page-header";
import { useMeta } from "@/components/providers/data-provider";
import { useTheme, type ThemePreference } from "@/components/providers/theme-provider";
import { Card } from "@/components/ui/primitives";
import { API_MODE, IS_LIVE } from "@/lib/api";
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
  return (
    <SettingsCard title="Change your password" description={PASSWORD_RULE}>
      <ChangePasswordForm />
    </SettingsCard>
  );
}

function SettingsCard({ title, description, children, className }: { title: string; description: string; children: React.ReactNode; className?: string }) {
  return (
    <Card className={cn("p-5", className)}>
      <h2 className="text-[0.9375rem] font-bold text-subheading">{title}</h2>
      <p className="mb-4 text-[0.8125rem] text-muted-foreground">{description}</p>
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
