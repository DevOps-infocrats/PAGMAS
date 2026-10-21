"use client";

import { Check, ChevronDown, X } from "lucide-react";
import { Dialog as D, DropdownMenu as DM, Popover as P, Select as S, Tooltip as T } from "radix-ui";
import * as React from "react";
import { cn } from "@/lib/utils/cn";

/* ---------------- Tooltip ---------------- */

export function TooltipProvider({ children }: { children: React.ReactNode }) {
  return <T.Provider delayDuration={200}>{children}</T.Provider>;
}

export function Tooltip({
  content,
  children,
  side = "top",
  className,
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  className?: string;
}) {
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          sideOffset={6}
          className={cn(
            "z-50 max-w-72 rounded-md border border-border bg-popover px-3 py-2 text-xs leading-relaxed text-popover-foreground shadow-md",
            className,
          )}
        >
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}

/* ---------------- Popover ---------------- */

export const Popover = P.Root;
export const PopoverTrigger = P.Trigger;

export function PopoverContent({ className, align = "start", ...props }: React.ComponentProps<typeof P.Content>) {
  return (
    <P.Portal>
      <P.Content
        align={align}
        sideOffset={6}
        className={cn("z-50 rounded-lg border border-border bg-popover text-popover-foreground shadow-lg outline-none", className)}
        {...props}
      />
    </P.Portal>
  );
}

/* ---------------- Dropdown menu ---------------- */

export const DropdownMenu = DM.Root;
export const DropdownMenuTrigger = DM.Trigger;
export const DropdownMenuRadioGroup = DM.RadioGroup;

export function DropdownMenuContent({ className, align = "end", ...props }: React.ComponentProps<typeof DM.Content>) {
  return (
    <DM.Portal>
      <DM.Content
        align={align}
        sideOffset={6}
        className={cn("z-50 min-w-48 rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg", className)}
        {...props}
      />
    </DM.Portal>
  );
}

export function DropdownMenuItem({ className, ...props }: React.ComponentProps<typeof DM.Item>) {
  return (
    <DM.Item
      className={cn(
        "flex cursor-pointer select-none items-center gap-2 rounded-md px-2.5 py-2 text-sm outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-accent [&_svg]:size-4 [&_svg]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuLabel({ className, ...props }: React.ComponentProps<typeof DM.Label>) {
  return <DM.Label className={cn("px-2.5 py-1.5 text-xs font-medium text-muted-foreground", className)} {...props} />;
}

export function DropdownMenuSeparator() {
  return <DM.Separator className="my-1 h-px bg-border" />;
}

export function DropdownMenuRadioItem({ className, children, ...props }: React.ComponentProps<typeof DM.RadioItem>) {
  return (
    <DM.RadioItem
      className={cn(
        "relative flex cursor-pointer select-none items-center rounded-md py-2 pl-8 pr-2.5 text-sm outline-none data-[highlighted]:bg-accent",
        className,
      )}
      {...props}
    >
      <span className="absolute left-2.5 flex size-3.5 items-center justify-center">
        <DM.ItemIndicator>
          <span className="block size-2 rounded-full bg-primary" />
        </DM.ItemIndicator>
      </span>
      {children}
    </DM.RadioItem>
  );
}

/* ---------------- Select (short lists) ---------------- */

export interface SelectOption {
  value: string;
  label: string;
}

export function Select({
  value,
  onValueChange,
  options,
  placeholder,
  ariaLabel,
  className,
  disabled,
}: {
  value: string | undefined;
  onValueChange: (v: string) => void;
  options: SelectOption[];
  placeholder?: string;
  ariaLabel: string;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <S.Root value={value ?? ""} onValueChange={onValueChange} disabled={disabled}>
      <S.Trigger
        aria-label={ariaLabel}
        className={cn(
          "inline-flex h-9 items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 disabled:opacity-50 data-[placeholder]:text-subtle-foreground",
          className,
        )}
      >
        <S.Value placeholder={placeholder} />
        <S.Icon>
          <ChevronDown className="size-4 text-muted-foreground" />
        </S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content
          position="popper"
          sideOffset={6}
          className="z-50 max-h-80 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-lg"
        >
          <S.Viewport className="p-1">
            {options.map((o) => (
              <S.Item
                key={o.value}
                value={o.value}
                className="relative flex cursor-pointer select-none items-center rounded-md py-2 pl-8 pr-3 text-sm outline-none data-[highlighted]:bg-accent"
              >
                <S.ItemIndicator className="absolute left-2.5">
                  <Check className="size-4 text-primary" />
                </S.ItemIndicator>
                <S.ItemText>{o.label}</S.ItemText>
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  );
}

/* ---------------- Dialog & Sheet ---------------- */

export const Dialog = D.Root;
export const DialogTitle = D.Title;
export const DialogDescription = D.Description;

export function DialogContent({
  className,
  children,
  hideClose,
  ...props
}: React.ComponentProps<typeof D.Content> & { hideClose?: boolean }) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-black/40" />
      <D.Content
        className={cn(
          "fixed left-1/2 top-[12vh] z-50 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 rounded-xl border border-border bg-popover text-popover-foreground shadow-2xl outline-none",
          className,
        )}
        {...props}
      >
        {children}
        {!hideClose && (
          <D.Close className="absolute right-3 top-3 rounded-md p-1.5 text-muted-foreground hover:bg-accent" aria-label="Close">
            <X className="size-4" />
          </D.Close>
        )}
      </D.Content>
    </D.Portal>
  );
}

export function SheetContent({ className, children, ...props }: React.ComponentProps<typeof D.Content>) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-black/40" />
      <D.Content className={cn("fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-sidebar shadow-2xl outline-none", className)} {...props}>
        {children}
      </D.Content>
    </D.Portal>
  );
}
