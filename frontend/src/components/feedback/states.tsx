import { AlertTriangle, Inbox, Loader2, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";

export function EmptyState({
  title = "No data",
  description,
  icon: Icon = Inbox,
  className,
  action,
}: {
  title?: string;
  description?: string;
  icon?: React.ComponentType<{ className?: string }>;
  className?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 px-6 py-10 text-center", className)}>
      <div className="flex size-10 items-center justify-center rounded-full bg-muted">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="max-w-sm text-[13px] text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: Error | string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div role="alert" className={cn("flex flex-col items-center justify-center gap-2 px-6 py-10 text-center", className)}>
      <div className="flex size-10 items-center justify-center rounded-full bg-critical-soft">
        <AlertTriangle className="size-5 text-critical-text" />
      </div>
      <p className="text-sm font-medium">Couldn&apos;t load this data</p>
      <p className="max-w-sm text-[13px] text-muted-foreground">{typeof error === "string" ? error : error.message}</p>
      {onRetry && (
        <Button size="sm" onClick={onRetry} className="mt-1">
          <RotateCw /> Try again
        </Button>
      )}
    </div>
  );
}

/** Spinner + text so a loading area never looks empty. */
export function LoadingLabel({ text = "Loading data…", className }: { text?: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-xs font-medium text-muted-foreground", className)}>
      <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden />
      {text}
    </span>
  );
}

export function ChartSkeleton({ height = 280, text = "Loading chart…" }: { height?: number; text?: string }) {
  return (
    <div className="relative" style={{ height }} aria-label={text} role="status">
      <div className="flex h-full items-end gap-3 px-2 pb-2 opacity-80">
        {[55, 80, 40, 90, 65, 75, 50, 85, 60, 70].map((h, i) => (
          <div key={i} className="skeleton flex-1 rounded-t" style={{ height: `${h}%` }} />
        ))}
      </div>
      <div className="absolute inset-0 flex items-center justify-center">
        <LoadingLabel text={text} className="rounded-full border border-border bg-card px-3 py-1.5 shadow-sm" />
      </div>
    </div>
  );
}

export function KpiSkeleton() {
  return (
    <div className="space-y-3 p-5" role="status" aria-label="Loading metric">
      <Skeleton className="h-3.5 w-28" />
      <Skeleton className="h-8 w-24" />
      <LoadingLabel />
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4" role="status" aria-label="Loading table">
      <LoadingLabel text="Loading table…" className="mb-1" />
      <Skeleton className="h-8 w-full" />
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading page">
      <LoadingLabel text="Loading dashboard…" className="text-sm" />
      <div className="space-y-2">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-7 w-72" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="rounded-lg border border-border bg-card">
            <KpiSkeleton />
          </div>
        ))}
      </div>
      <div className="rounded-lg border border-border bg-card p-5">
        <ChartSkeleton />
      </div>
    </div>
  );
}
