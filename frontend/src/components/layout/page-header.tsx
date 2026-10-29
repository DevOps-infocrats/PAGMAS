import Link from "next/link";
import { ArrowRight, CalendarDays, ChevronRight, Info } from "lucide-react";
import { cn } from "@/lib/utils/cn";

export interface Crumb {
  label: string;
  href?: string;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-1 text-[12.5px] font-medium text-muted-foreground">
        {items.map((c, i) => (
          <li key={`${c.label}-${i}`} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="size-3.5 text-subtle-foreground/70" aria-hidden />}
            {c.href && i < items.length - 1 ? (
              <Link href={c.href} className="rounded px-0.5 transition-colors hover:text-primary hover:underline">
                {c.label}
              </Link>
            ) : (
              <span aria-current={i === items.length - 1 ? "page" : undefined} className={cn("px-0.5", i === items.length - 1 && "text-foreground")}>
                {c.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  meta,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  breadcrumbs?: Crumb[];
  actions?: React.ReactNode;
  meta?: React.ReactNode;
}) {
  return (
    <header className="relative overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <span className="brand-gradient absolute inset-x-0 top-0 h-[3px]" aria-hidden />
      <div className="hero-surface flex flex-col gap-4 px-6 pb-5 pt-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 space-y-1.5">
          {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
          <h1 className="text-brand w-fit text-[25px] font-extrabold tracking-tight">{title}</h1>
          {description && <p className="text-sm font-medium text-subheading/80">{description}</p>}
          {meta && <div className="flex flex-wrap items-center gap-2 pt-1">{meta}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </header>
  );
}

/**
 * Title bar of the analytics pages: breadcrumb, "<scope> / <view>" title, reporting period, controls on the
 * right and an optional filter row underneath. Same look on every page.
 */
export function TitleBar({
  breadcrumbs,
  title,
  view,
  period,
  note,
  aside,
  children,
  tabs,
  sticky,
  compact,
}: {
  breadcrumbs?: Crumb[];
  /** Scope: state / block / GP name or the page name */
  title: React.ReactNode;
  /** Current view (the sidebar sub-item) */
  view?: React.ReactNode;
  /** Reporting period / context line under the title */
  period?: React.ReactNode;
  /** Short plain sentence next to the period */
  note?: React.ReactNode;
  aside?: React.ReactNode;
  /** Filter row (pickers) */
  children?: React.ReactNode;
  /** Tab strip between the title and the filters */
  tabs?: React.ReactNode;
  sticky?: boolean;
  /** Shorter bar (less padding, slightly smaller title) for table-first pages */
  compact?: boolean;
}) {
  return (
    <header className={cn("relative overflow-hidden rounded-xl border border-border bg-card shadow-sm", sticky && "sticky top-[4.25rem] z-20")}>
      <span className="brand-gradient absolute inset-x-0 top-0 h-[3px]" aria-hidden />
      <div className={cn("hero-surface flex flex-col lg:flex-row lg:items-center lg:justify-between", compact ? "gap-2 px-5 pb-2.5 pt-3.5" : "gap-3 px-6 pb-4 pt-5")}>
        <div className={cn("min-w-0", compact ? "space-y-1" : "space-y-1.5")}>
          {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
          <h1 className={cn("flex min-w-0 flex-wrap items-baseline gap-x-2.5 font-extrabold leading-tight tracking-tight", compact ? "text-[21px]" : "text-[25px]")}>
            <span className="text-brand">{title}</span>
            {view && (
              <>
                <span className="font-light text-subtle-foreground/60" aria-hidden>
                  /
                </span>
                <span className="font-bold text-subheading">{view}</span>
              </>
            )}
          </h1>
          {(period || note) && (
            <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px] text-muted-foreground">
              {period && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-card/80 px-2.5 py-0.5 font-medium text-foreground">
                  <CalendarDays className="size-3.5 text-primary" aria-hidden />
                  {period}
                </span>
              )}
              {note && <span>{note}</span>}
            </p>
          )}
        </div>
        {aside && <div className="flex flex-wrap items-center gap-2 lg:justify-end">{aside}</div>}
      </div>
      {tabs && <div className="border-t border-border px-6 py-2">{tabs}</div>}
      {children && (
        <div className={cn("grid grid-cols-1 gap-x-4 gap-y-2.5 border-t border-border sm:grid-cols-2 lg:grid-cols-4", compact ? "px-5 py-2.5" : "px-6 py-3.5")}>{children}</div>
      )}
    </header>
  );
}

/** One plain-language line that says what the current view shows. */
export function ViewHint({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 text-[13px] leading-relaxed text-muted-foreground">
      <Info className="mt-[3px] size-3.5 shrink-0 text-primary" aria-hidden />
      <span>{children}</span>
    </p>
  );
}

/** Links to the other views of a page (shown under a summary). */
export function RelatedViews({ label, title, items }: { label: string; title: string; items: { href: string; title: string }[] }) {
  return (
    <nav aria-label={label} className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
      <span className="mr-1 text-[13px] font-medium text-muted-foreground">{title}</span>
      {items.map((v) => (
        <Link
          key={v.href}
          href={v.href}
          className="group inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-1.5 text-[13px] font-medium shadow-xs transition-colors hover:border-primary/40 hover:bg-primary-soft hover:text-primary"
        >
          {v.title} <ArrowRight className="size-3.5 text-primary transition-transform group-hover:translate-x-0.5" aria-hidden />
        </Link>
      ))}
    </nav>
  );
}

/** Cloudflare-style section header: title, one-line description, optional action. */
export function SectionHeader({
  title,
  description,
  action,
  id,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  id?: string;
}) {
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h2 id={id} className="text-base font-bold text-subheading">
          {title}
        </h2>
        {description && <p className="text-[13px] text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}
