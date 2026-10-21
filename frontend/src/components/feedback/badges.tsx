"use client";

import { CircleCheck, CircleDashed, CircleMinus, CircleX, Info, TriangleAlert } from "lucide-react";
import { useMeta } from "@/components/providers/data-provider";
import { Tooltip } from "@/components/ui/overlays";
import { IS_LIVE } from "@/lib/api";
import { THRESHOLDS } from "@/lib/metrics/definitions";
import { cn } from "@/lib/utils/cn";
import { formatDate, formatPercent } from "@/lib/utils/format";
import type { AmcStatus, GpLifecycle, HotoStatus } from "@/types";

type Tone = "good" | "warning" | "critical" | "neutral" | "info";

const TONE: Record<Tone, string> = {
  good: "bg-good-soft text-good-text",
  warning: "bg-warning-soft text-warning-text",
  critical: "bg-critical-soft text-critical-text",
  neutral: "bg-na-soft text-muted-foreground",
  info: "bg-primary-soft text-primary",
};

const ICON: Record<Tone, React.ComponentType<{ className?: string }>> = {
  good: CircleCheck,
  warning: TriangleAlert,
  critical: CircleX,
  neutral: CircleMinus,
  info: CircleDashed,
};

/** Status is never colour-only: every badge carries an icon and a text label. */
export function StatusBadge({ tone, children, className }: { tone: Tone; children: React.ReactNode; className?: string }) {
  const Icon = ICON[tone];
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", TONE[tone], className)}>
      <Icon className="size-3.5" />
      {children}
    </span>
  );
}

export function HotoBadge({ status }: { status: HotoStatus }) {
  if (status === "DONE") return <StatusBadge tone="good">Done</StatusBadge>;
  if (status === "PENDING") return <StatusBadge tone="warning">Pending</StatusBadge>;
  return <StatusBadge tone="neutral">Not applicable</StatusBadge>;
}

export function AmcBadge({ status }: { status: AmcStatus }) {
  return status === "AMC" ? <StatusBadge tone="info">AMC</StatusBadge> : <StatusBadge tone="neutral">Non-AMC</StatusBadge>;
}

export function LifecycleBadge({ status }: { status: GpLifecycle }) {
  if (status === "ACTIVE") return <StatusBadge tone="good">Active</StatusBadge>;
  if (status === "CONVERTED_NP") return <StatusBadge tone="warning">Converted to NP</StatusBadge>;
  if (status === "DEDUCTED") return <StatusBadge tone="neutral">Deducted from block</StatusBadge>;
  return <StatusBadge tone="critical">Permanently closed</StatusBadge>;
}

export function availabilityTone(v: number | null): Tone {
  if (v == null) return "neutral";
  if (v >= THRESHOLDS.healthy) return "good";
  if (v >= THRESHOLDS.penalty) return "warning";
  return "critical";
}

/** Availability value with band icon; NA is explicit and never shown as 0%. */
export function AvailabilityValue({ value }: { value: number | null }) {
  const tone = availabilityTone(value);
  if (value == null)
    return (
      <Tooltip content="Not reported for this week (NA). This is different from 0% availability.">
        <span className="inline-flex cursor-help items-center gap-1 text-muted-foreground">
          <CircleMinus className="size-3.5" /> NA
        </span>
      </Tooltip>
    );
  const Icon = ICON[tone];
  const color = tone === "good" ? "text-good-text" : tone === "warning" ? "text-warning-text" : "text-critical-text";
  return (
    <span className="tabular inline-flex items-center gap-1">
      <Icon className={cn("size-3.5", color)} />
      {formatPercent(value, 2)}
    </span>
  );
}

/** Data-source badge: "Live · data as of …" with the backend, "Demo data" in mock mode. */
export function DemoBadge({ className }: { className?: string }) {
  const meta = useMeta();
  if (IS_LIVE) {
    return (
      <Tooltip content={meta?.datasetFileName ? `Source: ${meta.datasetFileName}` : "Live data from the backend"}>
        <span
          className={cn(
            "inline-flex cursor-help items-center gap-1.5 rounded-full border border-good/40 bg-good-soft px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-good-text",
            className,
          )}
        >
          <span className="size-1.5 rounded-full bg-good" aria-hidden />
          {meta?.dataAsOf ? `Data as of ${formatDate(meta.dataAsOf)}` : "Live data"}
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip content="All figures are generated demo data (NEXT_PUBLIC_API_MODE=mock). No company data is shown.">
      <span
        className={cn(
          "inline-flex cursor-help items-center gap-1.5 rounded-full border border-warning/50 bg-warning-soft px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-warning-text",
          className,
        )}
      >
        <span className="size-1.5 rounded-full bg-warning" aria-hidden />
        Demo data
      </span>
    </Tooltip>
  );
}

export function InfoTip({ content, label }: { content: React.ReactNode; label: string }) {
  return (
    <Tooltip content={content}>
      <button type="button" aria-label={`About ${label}`} className="rounded text-subtle-foreground hover:text-foreground">
        <Info className="size-3.5" />
      </button>
    </Tooltip>
  );
}
