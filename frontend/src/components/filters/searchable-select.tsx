"use client";

import { Command } from "cmdk";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { useId, useState } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/overlays";
import { cn } from "@/lib/utils/cn";

export interface SearchableOption {
  value: string;
  label: string;
  hint?: string;
}

/** Searchable combobox for long option lists (circles, districts, blocks). */
export function SearchableSelect({
  value,
  onChange,
  options,
  placeholder = "Select…",
  label,
  disabled,
  className,
  allowClear,
  clearLabel = "All",
  hideLabel,
}: {
  value: string | undefined;
  onChange: (v: string | undefined) => void;
  options: SearchableOption[];
  placeholder?: string;
  /** Visible field label (also used as accessible name) */
  label: string;
  disabled?: boolean;
  className?: string;
  allowClear?: boolean;
  clearLabel?: string;
  /** Keep the label for screen readers only (compact toolbars). */
  hideLabel?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  const selected = options.find((o) => o.value === value);

  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <span className={cn("text-xs font-medium text-muted-foreground", hideLabel && "sr-only")}>{label}</span>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild disabled={disabled}>
          <button
            type="button"
            role="combobox"
            aria-expanded={open}
            aria-controls={listId}
            aria-label={label}
            className="inline-flex h-9 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-sm shadow-xs transition-colors hover:border-subtle-foreground/50 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 disabled:opacity-50 aria-expanded:border-ring aria-expanded:ring-2 aria-expanded:ring-ring/20"
          >
            <span className={cn("truncate", !selected && "text-subtle-foreground")}>
              {selected?.label ?? (allowClear && !value ? clearLabel : placeholder)}
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
          </button>
        </PopoverTrigger>
        <PopoverContent id={listId} className="w-[var(--radix-popover-trigger-width)] min-w-64 p-0">
          <Command loop>
            <div className="flex items-center gap-2 border-b border-border px-3">
              <Search className="size-4 text-subtle-foreground" />
              <Command.Input
                placeholder={`Search ${label.toLowerCase()}…`}
                className="h-10 w-full bg-transparent text-sm outline-none placeholder:text-subtle-foreground"
              />
            </div>
            <Command.List className="max-h-72 overflow-y-auto p-1">
              <Command.Empty className="px-3 py-6 text-center text-[13px] text-muted-foreground">No matches.</Command.Empty>
              {allowClear && (
                <Command.Item
                  value={`__all__ ${clearLabel}`}
                  onSelect={() => {
                    onChange(undefined);
                    setOpen(false);
                  }}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm data-[selected=true]:bg-accent"
                >
                  <Check className={cn("size-4 text-primary", value ? "opacity-0" : "opacity-100")} />
                  {clearLabel}
                </Command.Item>
              )}
              {options.map((o) => (
                <Command.Item
                  key={o.value}
                  value={`${o.label} ${o.hint ?? ""} ${o.value}`}
                  onSelect={() => {
                    onChange(o.value);
                    setOpen(false);
                  }}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm data-[selected=true]:bg-accent"
                >
                  <Check className={cn("size-4 shrink-0 text-primary", o.value === value ? "opacity-100" : "opacity-0")} />
                  <span className="truncate">{o.label}</span>
                  {o.hint && <span className="ml-auto shrink-0 text-xs text-subtle-foreground">{o.hint}</span>}
                </Command.Item>
              ))}
            </Command.List>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  );
}
