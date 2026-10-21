"use client";

import { ChevronLeft, ChevronRight, FileUp, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { EmptyState, ErrorState } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Card, Input } from "@/components/ui/primitives";
import type { ChainStep } from "@/lib/api";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils/cn";
import { formatCount } from "@/lib/utils/format";

/** Error card; "no Escalation Matrix uploaded yet" (404) gets a friendly empty state with a link to Data Operations. */
export function FieldError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  if (error instanceof ApiError && error.status === 404)
    return (
      <Card>
        <EmptyState icon={FileUp} title="No Escalation Matrix uploaded yet" description="Upload the Escalation Matrix workbook on Data Operations – on its own or together with the master data file." />
        <div className="pb-6 text-center">
          <Link href="/dashboard/operations" className="text-sm font-medium text-primary hover:underline">
            Go to Data Operations
          </Link>
        </div>
      </Card>
    );
  return (
    <Card>
      <ErrorState error={error} onRetry={onRetry} />
    </Card>
  );
}

/** Name + phone of one escalation step; a missing contact is flagged, an invalid number is marked. */
export function ChainCell({ step, compact = false }: { step: ChainStep | undefined; compact?: boolean }) {
  if (!step || !step.name) return <span className="text-xs font-medium text-critical-text">Missing</span>;
  return (
    <span className={cn("block min-w-0", compact ? "max-w-[150px]" : "max-w-[190px]")}>
      <span className="block truncate font-medium" title={step.name}>
        {step.name}
      </span>
      {step.role !== "frt" &&
        (step.phone ? (
          <span className={cn("tabular block text-[11px]", step.phoneValid ? "text-muted-foreground" : "text-warning-text")} title={step.phoneValid ? undefined : "Not a valid 10-digit mobile number"}>
            {step.phone}
            {!step.phoneValid && " ⚠"}
          </span>
        ) : (
          <span className="block text-[11px] text-subtle-foreground">no phone</span>
        ))}
    </span>
  );
}

/** Search box that reports its value once typing pauses. */
export function SearchBox({ onSearch, placeholder }: { onSearch: (v: string) => void; placeholder: string }) {
  const [text, setText] = useState("");
  useEffect(() => {
    const t = setTimeout(() => onSearch(text.trim()), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-xs font-medium text-muted-foreground">Search</span>
      <span className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-subtle-foreground" aria-hidden />
        <Input value={text} onChange={(e) => setText(e.target.value)} maxLength={80} placeholder={placeholder} className="h-9 pl-8" />
      </span>
    </label>
  );
}

export function Pager({ page, pages, total, pageSize, onPage, busy }: { page: number; pages: number; total: number; pageSize: number; onPage: (p: number) => void; busy?: boolean }) {
  if (total === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  return (
    <nav aria-label="Pages" className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-2.5 text-sm">
      <span className="text-muted-foreground">
        Showing {formatCount(from)}–{formatCount(to)} of {formatCount(total)}
      </span>
      <span className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => onPage(page - 1)} disabled={page <= 1 || busy}>
          <ChevronLeft /> Previous
        </Button>
        <span className="tabular text-muted-foreground">
          Page {page} of {pages}
        </span>
        <Button variant="outline" size="sm" onClick={() => onPage(page + 1)} disabled={page >= pages || busy}>
          Next <ChevronRight />
        </Button>
      </span>
    </nav>
  );
}

/** "Phone numbers partly hidden" note for non-admin users. */
export function MaskNote({ masked }: { masked?: boolean }) {
  if (!masked) return null;
  return <p className="text-xs text-muted-foreground">Phone numbers are partly hidden (98XXXXX144) – only admins see them in full.</p>;
}

export const step = (chain: ChainStep[], role: ChainStep["role"]) => chain.find((s) => s.role === role);
