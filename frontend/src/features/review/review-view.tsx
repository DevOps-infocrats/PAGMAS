"use client";

import { Check, ChevronLeft, ChevronRight, Download, Loader2, Maximize2, Presentation, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Logo } from "@/components/brand/logo";
import { ErrorState, PageSkeleton } from "@/components/feedback/states";
import { PeriodFilter } from "@/components/filters/filter-bar";
import { useMeta } from "@/components/providers/data-provider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/controls";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { useFilters } from "@/hooks/use-filters";
import { api, type ManagementReviewResponse } from "@/lib/api";
import { downloadManagementReviewPptx } from "@/lib/reports/report-service";
import { REVIEW_PAGES, REVIEW_PATH, reviewPageFrom, type ReviewPageId } from "@/lib/review-pages";
import { cn } from "@/lib/utils/cn";
import { formatDate } from "@/lib/utils/format";
import { PresentContext } from "./review-parts";
import { BlockNetworkTab, BlocksGpsTab, ExecutiveTab, GpNetworkTab, TargetsTab } from "./review-tabs";

const PAGES = REVIEW_PAGES;
type PageId = ReviewPageId;
const PAGE_IDS: string[] = PAGES.map((p) => p.id);
const PER_CIRCLE = new Set<string>(PAGES.filter((p) => "perCircle" in p).map((p) => p.id));

/**
 * Management Review: the report header (period + download) and ONE report page at a time. The page is
 * chosen from the sidebar sub-menu or the Previous / Next buttons and lives in the URL (?page=), so a
 * single page can be shared; opening the section shows page 1. Page and deck come from the same
 * backend payload, so the numbers always agree; the PPT download offers all five pages.
 */
export function ManagementReviewView() {
  const { period, filters, setFilters } = useFilters();
  const meta = useMeta();
  // Default reporting week = the latest *completed* week (never a partial week).
  useEffect(() => {
    if (!meta?.dataAsOf || filters.week) return;
    const done = meta.weeks.filter((w) => w.endDate <= meta.dataAsOf!);
    const last = done[done.length - 1];
    if (last && last.id !== meta.latestWeekId) {
      const prev = meta.weeks[meta.weeks.indexOf(last) - 1];
      setFilters({ week: last.id, compare: prev?.id ?? last.id });
    }
  }, [meta, filters.week, setFilters]);
  const params = useSearchParams();
  const { hrefTo } = useFilters();

  const q = useApiQuery(period ? `review:${period.weekId}:${period.compareWeekId}` : null, () =>
    api.getManagementReview({ weekId: period!.weekId, compareWeekId: period!.compareWeekId }),
  );
  const data = q.data;
  const pageId = reviewPageFrom(params.get("page"));
  const index = PAGE_IDS.indexOf(pageId);
  const page = PAGES[index];
  const prev = index > 0 ? PAGES[index - 1] : null;
  const next = index < PAGES.length - 1 ? PAGES[index + 1] : null;
  const pageHref = (id: string) => {
    const base = hrefTo(REVIEW_PATH);
    return `${base}${base.includes("?") ? "&" : "?"}page=${id}`;
  };

  const [presenting, setPresenting] = useState(false);
  // Fullscreen must be requested inside the click; if the browser refuses, the overlay still fills the window.
  const startPresenting = () => {
    setPresenting(true);
    document.documentElement.requestFullscreen?.().catch(() => undefined);
  };
  const stopPresenting = () => {
    setPresenting(false);
    if (document.fullscreenElement) document.exitFullscreen?.().catch(() => undefined);
  };
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogKey, setDialogKey] = useState(0); // new key per opening -> pre-filled from the visible pages
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const openDialog = () => {
    setDialogKey((k) => k + 1);
    setDialogOpen(true);
  };

  return (
    <div className="mx-auto w-full max-w-[min(1080px,100%)] space-y-4 lg:w-[max(900px,85%)]">
      {/* 85% of the content area (never under 900px, never over 1080px), so the report reads as a page on a laptop too */}
      {/* ---------------- Compact report header: title + actions, then the period pickers ---------------- */}
      <Card className="overflow-hidden p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <span className="shrink-0 rounded-lg bg-card p-1.5 shadow-sm ring-1 ring-border">
              <Logo variant="full" width={40} eager />
            </span>
            <div className="min-w-0">
              <h1 className="text-brand w-fit text-[21px] font-extrabold leading-tight tracking-tight">Management Review</h1>
              <p
                className="truncate text-[13px] text-muted-foreground"
                title="The default week is the latest completed week in the file. All figures are recalculated from the active workbook whenever a new file is uploaded."
              >
                {period ? (
                  <>
                    <span className="font-medium text-foreground">
                      {period.week.label} vs {period.compareWeek.label}
                    </span>
                    {` · ${formatDate(period.week.startDate)} – ${formatDate(period.week.endDate)}`}
                  </>
                ) : (
                  "Loading period…"
                )}
                {data && ` · data as of ${formatDate(data.dataAsOf)} · ${data.sourceFile}`}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="outline" onClick={startPresenting} disabled={!data}>
              <Maximize2 /> Present
            </Button>
            <Button variant="primary" onClick={openDialog} disabled={!period || !data}>
              <Presentation /> Download PPT
            </Button>
          </div>
        </div>
        <div className="border-t border-border bg-muted/40 px-5 py-3">
          <PeriodFilter />
        </div>
      </Card>

      {message && (
        <p role="status" className={cn("flex items-center gap-2 rounded-md border px-4 py-2.5 text-sm", message.error ? "border-critical/30 bg-critical-soft text-critical-text" : "border-good/30 bg-good-soft text-good-text")}>
          {!message.error && <Check className="size-4" aria-hidden />}
          {message.text}
        </p>
      )}

      {/* ---------------- Pages ---------------- */}
      {q.error ? (
        <Card>
          <ErrorState error={q.error} onRetry={q.reload} />
        </Card>
      ) : !data ? (
        <PageSkeleton />
      ) : (
        <div className="space-y-4">
          {presenting ? (
            <PresentationMode
              number={index + 1}
              total={PAGES.length}
              title={page.title}
              weekLabel={`${data.week.label} vs ${data.compareWeek.label}`}
              prevHref={prev ? pageHref(prev.id) : null}
              nextHref={next ? pageHref(next.id) : null}
              onClose={stopPresenting}
            >
              <PageContent key={page.id} id={page.id} r={data} />
            </PresentationMode>
          ) : (
            <ReportPage key={page.id} id={page.id} number={index + 1} total={PAGES.length} title={page.title} hint={page.hint} weekLabel={`${data.week.label} vs ${data.compareWeek.label}`}>
              <PageContent id={page.id} r={data} />
            </ReportPage>
          )}
          <nav aria-label="Report page navigation" className="flex flex-wrap items-center justify-between gap-3">
            {prev ? (
              <Link href={pageHref(prev.id)} className="group inline-flex max-w-[48%] items-center gap-2 rounded-lg border border-border bg-card px-4 py-2.5 text-sm shadow-xs transition-colors hover:bg-accent">
                <ChevronLeft className="size-4 shrink-0 text-muted-foreground group-hover:text-foreground" aria-hidden />
                <span className="min-w-0">
                  <span className="block text-xs text-muted-foreground">Previous · page {index}</span>
                  <span className="block truncate font-semibold">{prev.title}</span>
                </span>
              </Link>
            ) : (
              <span />
            )}
            {next && (
              <Link href={pageHref(next.id)} className="group inline-flex max-w-[48%] items-center gap-2 rounded-lg border border-primary/30 bg-primary-soft/50 px-4 py-2.5 text-right text-sm shadow-xs transition-colors hover:bg-primary-soft">
                <span className="min-w-0">
                  <span className="block text-xs text-muted-foreground">Next · page {index + 2}</span>
                  <span className="block truncate font-semibold">{next.title}</span>
                </span>
                <ChevronRight className="size-4 shrink-0 text-primary" aria-hidden />
              </Link>
            )}
          </nav>
        </div>
      )}

      {data && period && (
        <DownloadDialog
          key={dialogKey}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          r={data}
          initialPages={PAGE_IDS}
          onDone={setMessage}
          period={{ weekId: period.weekId, compareWeekId: period.compareWeekId }}
        />
      )}
    </div>
  );
}

function PageContent({ id, r }: { id: PageId; r: ManagementReviewResponse }) {
  if (id === "summary") return <ExecutiveTab r={r} />;
  if (id === "targets") return <TargetsTab r={r} />;
  if (id === "blocks-gps") return <BlocksGpsTab r={r} />;
  if (id === "block-network") return <BlockNetworkTab r={r} />;
  return <GpNetworkTab r={r} />;
}

/** Slide-style header and footer shared by the on-page view and presentation mode. */
function PageHead({ id, number, total, title, hint }: { id?: string; number: number; total: number; title: string; hint?: string }) {
  return (
    <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border bg-muted/40 px-5 py-3">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground">{number}</span>
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-primary">
            Page {number} of {total}
          </p>
          <h2 id={id ? `sec-${id}-title` : undefined} className="truncate text-base font-bold text-subheading sm:text-lg">
            {title}
          </h2>
          {hint && <p className="truncate text-[13px] text-muted-foreground">{hint}</p>}
        </div>
      </div>
      <Logo variant="wordmark" width={84} className="shrink-0" />
    </header>
  );
}

function PageFoot({ number, total, weekLabel }: { number: number; total: number; weekLabel: string }) {
  return (
    <footer className="flex shrink-0 items-center justify-between gap-3 border-t border-border bg-muted/30 px-5 py-2 text-[11px] text-muted-foreground">
      <span className="truncate">Pratap · Management Governance Review · {weekLabel}</span>
      <span className="shrink-0 font-medium">
        {number} / {total}
      </span>
    </footer>
  );
}

/** One report page: framed like a sheet (accent bar, border, header, footer) so it reads as a single page. */
function ReportPage({ id, number, total, title, hint, weekLabel, children }: { id: string; number: number; total: number; title: string; hint: string; weekLabel: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={`sec-${id}-title`} id={`sec-${id}`} className="scroll-mt-24 overflow-hidden rounded-lg border border-border bg-card shadow-sm">
      <div className="brand-gradient h-1" aria-hidden />
      <PageHead id={id} number={number} total={total} title={title} hint={hint} />
      <div className="p-4 sm:p-5">{children}</div>
      <PageFoot number={number} total={total} weekLabel={weekLabel} />
    </section>
  );
}

// Presentation frame: every page is the same 16:9 sheet, scaled to the screen like a slide.
const SLIDE_W = 1440;
const SLIDE_H = 810;
const MIN_TEXT_SCALE = 0.8; // never shrink a dense page below this; scroll inside the slide instead
/** Scale of the 16:9 slide that fits the window, leaving room for the controls below it. */
const slideFit = () => Math.min((window.innerWidth - 32) / SLIDE_W, (window.innerHeight - 76) / SLIDE_H);

function PresentationMode({
  number,
  total,
  title,
  weekLabel,
  prevHref,
  nextHref,
  onClose,
  children,
}: {
  number: number;
  total: number;
  title: string;
  weekLabel: string;
  prevHref: string | null;
  nextHref: string | null;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [fit, setFit] = useState(slideFit);
  const wentFullscreen = useRef(false);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  }, [onClose]);

  // Enter once: fullscreen (when the browser allows it), fit-to-window sizing, no page scroll behind.
  useEffect(() => {
    const resize = () => setFit(slideFit());
    window.addEventListener("resize", resize);
    // Browser Esc leaves fullscreen without a keydown, so leaving fullscreen also ends the presentation.
    const onFs = () => {
      if (document.fullscreenElement) wentFullscreen.current = true;
      else if (wentFullscreen.current) close.current();
    };
    document.addEventListener("fullscreenchange", onFs);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("resize", resize);
      document.removeEventListener("fullscreenchange", onFs);
      document.body.style.overflow = prevOverflow;
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t?.closest("[role=listbox],[role=combobox],input,textarea,select")) return;
      if (e.key === "Escape") close.current();
      else if ((e.key === "ArrowRight" || e.key === "PageDown") && nextHref) router.replace(nextHref, { scroll: false });
      else if ((e.key === "ArrowLeft" || e.key === "PageUp") && prevHref) router.replace(prevHref, { scroll: false });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nextHref, prevHref, router]);

  const nav = "inline-flex h-9 items-center gap-1.5 rounded-md px-3 text-sm font-medium text-white/90 hover:bg-white/10 aria-disabled:pointer-events-none aria-disabled:opacity-30";
  return createPortal(
    <div role="dialog" aria-modal="true" aria-label={`Presentation – page ${number}: ${title}`} className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-slate-950/95 p-4">
      <div style={{ width: SLIDE_W * fit, height: SLIDE_H * fit }}>
        <div
          style={{ width: SLIDE_W, height: SLIDE_H, transform: `scale(${fit})`, transformOrigin: "top left" }}
          className="flex flex-col overflow-hidden rounded-xl border-2 border-primary/30 bg-card text-foreground shadow-2xl"
        >
          <div className="brand-gradient h-1.5 shrink-0" aria-hidden />
          <PageHead number={number} total={total} title={title} />
          <FitBody>
            <PresentContext.Provider value>{children}</PresentContext.Provider>
          </FitBody>
          <PageFoot number={number} total={total} weekLabel={weekLabel} />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Link href={prevHref ?? "#"} replace scroll={false} aria-disabled={!prevHref} className={nav}>
          <ChevronLeft className="size-4" /> Previous
        </Link>
        <span className="min-w-14 text-center text-sm text-white/70">
          {number} / {total}
        </span>
        <Link href={nextHref ?? "#"} replace scroll={false} aria-disabled={!nextHref} className={nav}>
          Next <ChevronRight className="size-4" />
        </Link>
        <span className="mx-2 h-5 w-px bg-white/20" aria-hidden />
        <button type="button" onClick={onClose} className={nav}>
          <X className="size-4" /> Exit (Esc)
        </button>
      </div>
    </div>,
    document.body,
  );
}

/** Shrinks the page content to fit the slide body (down to MIN_TEXT_SCALE), then scrolls inside the slide. */
function FitBody({ children }: { children: React.ReactNode }) {
  const outer = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [naturalHeight, setNaturalHeight] = useState(0);

  useEffect(() => {
    const o = outer.current;
    const i = inner.current;
    if (!o || !i) return;
    const measure = () => {
      const avail = o.clientHeight;
      const natural = i.offsetHeight; // layout height, unaffected by the transform
      if (!avail || !natural) return;
      setNaturalHeight(natural);
      setScale((s) => {
        // Content is laid out at width 100%/s, so its height grows as s shrinks; iterate to a stable fit.
        const target = Math.max(MIN_TEXT_SCALE, Math.min(1, s * Math.sqrt(avail / (natural * s))));
        return Math.abs(target - s) < 0.01 ? s : target;
      });
    };
    const ro = new ResizeObserver(measure);
    ro.observe(o);
    ro.observe(i);
    measure();
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={outer} className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
      <div style={{ height: naturalHeight ? naturalHeight * scale : undefined }}>
        <div ref={inner} className="p-5" style={{ width: `${100 / scale}%`, transform: `scale(${scale})`, transformOrigin: "top left" }}>
          {children}
        </div>
      </div>
    </div>
  );
}

function Choice({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: () => void; label: string; hint?: string; disabled?: boolean }) {
  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 text-sm transition-colors",
        checked ? "border-primary/50 bg-primary-soft/40" : "border-border bg-card hover:bg-accent",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <Checkbox checked={checked} onCheckedChange={onChange} disabled={disabled} className="mt-0.5" aria-label={label} />
      <span className="min-w-0">
        <span className="block font-medium">{label}</span>
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </span>
    </label>
  );
}

function SelectAll({ all, chosen, onChange }: { all: string[]; chosen: string[]; onChange: (v: string[]) => void }) {
  const everything = all.every((x) => chosen.includes(x));
  return (
    <button type="button" onClick={() => onChange(everything ? [] : all)} className="text-xs font-medium text-primary hover:underline">
      {everything ? "Clear all" : "Select all"}
    </button>
  );
}

/** Asked before every download: which pages and circles go into the deck (all circles by default). */
function DownloadDialog({
  open,
  onOpenChange,
  r,
  initialPages,
  period,
  onDone,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  r: ManagementReviewResponse;
  initialPages: string[];
  period: { weekId: string; compareWeekId: string };
  onDone: (m: { text: string; error?: boolean }) => void;
}) {
  const [pages, setPages] = useState<string[]>(initialPages.length ? initialPages : PAGE_IDS);
  const [circles, setCircles] = useState<string[]>(r.circles.map((c) => c.id));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const flip = (list: string[], set: (v: string[]) => void, id: string, order: string[]) =>
    set(list.includes(id) ? list.filter((x) => x !== id) : order.filter((x) => x === id || list.includes(x)));

  const needsCircle = pages.some((s) => PER_CIRCLE.has(s));
  const slides = 3 + pages.reduce((n, s) => n + (PER_CIRCLE.has(s) ? circles.length : 1), 0);
  const problem = !pages.length ? "Choose at least one page." : needsCircle && !circles.length ? "Choose at least one circle for pages 3–5." : null;

  const generate = async () => {
    if (problem) return;
    setBusy(true);
    setError(null);
    try {
      const name = await downloadManagementReviewPptx(period, { sections: pages, circles: needsCircle ? circles : [] });
      onDone({ text: `Downloaded ${name} (${slides} slides).` });
      onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setBusy(false);
    }
  };

  const circleOrder = r.circles.map((c) => c.id);
  return (
    <Dialog open={open} onOpenChange={(v) => !busy && onOpenChange(v)}>
      <DialogContent className="max-w-2xl">
        <div className="max-h-[76vh] space-y-5 overflow-y-auto p-6">
          <div className="flex items-start gap-3">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
              <Presentation className="size-5" aria-hidden />
            </span>
            <div>
              <DialogTitle className="text-lg font-semibold">Download Management Review (PPT)</DialogTitle>
              <DialogDescription className="mt-1 text-sm text-muted-foreground">
                Week {r.week.number} vs Week {r.compareWeek.number} · the cover with the Pratap logo, the index and the closing slide are always included.
              </DialogDescription>
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold">Pages</span>
              <SelectAll all={PAGE_IDS} chosen={pages} onChange={setPages} />
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {PAGES.map((p, i) => (
                <Choice key={p.id} checked={pages.includes(p.id)} onChange={() => flip(pages, setPages, p.id, PAGE_IDS)} label={`${i + 1} · ${p.title}`} hint={"perCircle" in p ? `${p.hint} · one slide per circle` : p.hint} />
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold">Circles {needsCircle ? <span className="font-normal text-muted-foreground">(pages 3–5)</span> : <span className="font-normal text-muted-foreground">(only used by pages 3–5)</span>}</span>
              <SelectAll all={circleOrder} chosen={circles} onChange={setCircles} />
            </div>
            <div className="flex flex-wrap gap-2">
              {r.circles.map((c) => (
                <Choice key={c.id} checked={circles.includes(c.id)} onChange={() => flip(circles, setCircles, c.id, circleOrder)} label={`${c.name} (${c.code})`} disabled={!needsCircle} />
              ))}
            </div>
          </div>

          {(problem || error) && (
            <p role="alert" className="rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
              {problem ?? error}
            </p>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <span className="text-sm text-muted-foreground">{problem ? "—" : `${slides} slides will be generated`}</span>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
                Cancel
              </Button>
              <Button variant="primary" onClick={generate} disabled={busy || !!problem}>
                {busy ? <Loader2 className="animate-spin" /> : <Download />}
                {busy ? "Building PPT…" : "Generate & download"}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
