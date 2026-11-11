"use client";

import { Check, ChevronDown } from "lucide-react";
import { Select as S } from "radix-ui";
import type { GpCategory } from "@/lib/api";
import { cn } from "@/lib/utils/cn";

/**
 * GP classification of the daily progress (backend: app/tickets/task.py CATEGORIES). Only E "Letter Submission Done"
 * counts as achieved. Colours come from the dashboard theme tokens (light and dark).
 */
export const GP_CATEGORIES: { code: GpCategory; label: string; color: string; info: string }[] = [
  { code: "A", label: "Rectification Done", color: "var(--good)", info: "Rectification of the GP is completed." },
  { code: "B", label: "Ready for Letter Submitted", color: "var(--series-1)", info: "The GP is ready and its letter can be submitted." },
  { code: "C", label: "Revisit Required", color: "var(--warning)", info: "The GP has to be visited again." },
  { code: "D", label: "Non-Doable – Proposed", color: "var(--critical)", info: "The GP is proposed as not doable." },
  { code: "E", label: "Letter Submission Done", color: "var(--series-7)", info: "The letter of the GP is submitted – the only category counted as Achieved." },
];
/** What the FE / Area Manager may choose in the daily progress; B and E come from the AM / SME / COH review. */
export const FE_CATEGORIES: GpCategory[] = ["A", "C", "D"];
export const CATEGORY = Object.fromEntries(GP_CATEGORIES.map((c) => [c.code, c])) as Record<GpCategory, (typeof GP_CATEGORIES)[number]>;

const soft = (color: string) => ({ background: `color-mix(in srgb, ${color} 14%, transparent)`, color });

/** Coloured badge of a GP category ("Not classified" when none was chosen yet). */
export function GpCategoryBadge({ code, className }: { code: GpCategory | null | undefined; className?: string }) {
  if (!code) return <span className={cn("inline-flex rounded-full bg-muted px-2 py-0.5 text-[0.6875rem] font-semibold text-muted-foreground", className)}>Not classified</span>;
  const c = CATEGORY[code];
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold", className)} style={soft(c.color)} title={c.info}>
      <span className="size-1.5 shrink-0 rounded-full" style={{ background: c.color }} aria-hidden />
      {c.label}
    </span>
  );
}

/** Daily Achievement dropdown, each category with its colour (`options` = the choosable codes; the current value is
 * always shown). */
export function GpCategorySelect({
  value,
  onChange,
  disabled,
  ariaLabel,
  options = FE_CATEGORIES,
}: {
  value: GpCategory | null;
  onChange: (v: GpCategory) => void;
  disabled?: boolean;
  ariaLabel: string;
  options?: GpCategory[];
}) {
  const c = value ? CATEGORY[value] : null;
  const shown = GP_CATEGORIES.filter((o) => options.includes(o.code) || o.code === value);
  return (
    <S.Root value={value ?? ""} onValueChange={(v) => onChange(v as GpCategory)} disabled={disabled}>
      <S.Trigger
        aria-label={ariaLabel}
        className="inline-flex h-8 w-[13.125rem] items-center justify-between gap-2 rounded-md border border-subtle-foreground/40 bg-card px-2.5 text-left text-[0.75rem] font-semibold text-foreground shadow-xs transition-colors hover:border-subtle-foreground/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 disabled:opacity-50 data-[state=open]:border-ring"
        style={c ? { borderColor: `color-mix(in srgb, ${c.color} 55%, transparent)`, background: `color-mix(in srgb, ${c.color} 8%, var(--card))` } : undefined}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {c && <span className="size-2 shrink-0 rounded-full" style={{ background: c.color }} aria-hidden />}
          <span className={cn("truncate", !c && "font-normal text-muted-foreground")}>
            <S.Value placeholder="Select status" />
          </span>
        </span>
        <S.Icon>
          <ChevronDown className="size-3.5 shrink-0 text-foreground/70" />
        </S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content position="popper" sideOffset={4} className="z-50 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-lg">
          <S.Viewport className="p-1">
            {shown.map((o) => (
              <S.Item
                disabled={!options.includes(o.code)}
                key={o.code}
                value={o.code}
                className="relative flex cursor-pointer select-none items-center gap-2 rounded-md py-1.5 pl-7 pr-3 text-[0.78125rem] font-medium outline-none data-[highlighted]:bg-accent data-[state=checked]:font-semibold data-[disabled]:cursor-default data-[disabled]:opacity-50"
              >
                <S.ItemIndicator className="absolute left-2">
                  <Check className="size-3.5" style={{ color: o.color }} />
                </S.ItemIndicator>
                <span className="size-2 shrink-0 rounded-full" style={{ background: o.color }} aria-hidden />
                <S.ItemText>{o.label}</S.ItemText>
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  );
}
