"use client";

/**
 * FRT view of the GP-wise task (User Tickets, FRT login only): compact proof chips with thumbnails, the FE-check badge,
 * the summary cards and the 3-step guide. Display only – the rules (remark + photo, camera on a phone, FE check) stay in
 * ticket-task.tsx and the backend.
 */

import { CheckCircle2, Clock, FileText, Info, MapPin, Undo2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { ticketApi, type GeoFile, type TicketProofFile, type TicketTaskGp } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { ticketTime } from "./ticket-parts";

const isImage = (name: string, type?: string) => /^image\//.test(type ?? "") || /\.(jpe?g|png)$/i.test(name);

/** A saved proof file: thumbnail (images) or a file icon; click opens it, the pin opens the photo's location. */
function SavedChip({ f }: { f: TicketProofFile }) {
  const geo = f.latitude != null && f.longitude != null;
  const title = `${f.fileName} · uploaded ${ticketTime(f.uploadedAt)}${geo ? ` · location ${f.latitude}, ${f.longitude}${f.capturedAt ? ` · taken ${ticketTime(f.capturedAt)}` : ""}` : ""}`;
  return (
    <span className="relative inline-flex">
      <a
        href={ticketApi.progressFileUrl(f.id, f.previewable)}
        target="_blank"
        rel="noopener noreferrer"
        title={title}
        aria-label={`Open ${f.fileName}`}
        className="flex size-10 items-center justify-center overflow-hidden rounded-md border border-border bg-muted hover:ring-2 hover:ring-primary/40"
      >
        {f.previewable && isImage(f.fileName, f.contentType) ? (
          // eslint-disable-next-line @next/next/no-img-element -- a private proof file (same-origin API), not a static asset
          <img src={ticketApi.progressFileUrl(f.id, true)} alt="" loading="lazy" className="size-full object-cover" />
        ) : (
          <FileText className="size-4 text-primary" aria-hidden />
        )}
      </a>
      {geo && (
        <a
          href={`https://www.google.com/maps?q=${f.latitude},${f.longitude}`}
          target="_blank"
          rel="noopener noreferrer"
          title={`Location ${f.latitude}, ${f.longitude}${f.capturedAt ? ` · taken ${ticketTime(f.capturedAt)}` : ""}`}
          aria-label={`Location of ${f.fileName}`}
          className="absolute -bottom-1 -right-1 flex size-4 items-center justify-center rounded-full bg-good text-white ring-2 ring-card"
        >
          <MapPin className="size-2.5" aria-hidden />
        </a>
      )}
    </span>
  );
}

/** A file waiting for the next submission: thumbnail from the browser, remove button. */
function DraftChip({ file, onRemove, disabled }: { file: File; onRemove: () => void; disabled: boolean }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!isImage(file.name, file.type)) return;
    // read in the browser (nothing is uploaded); ignored once the chip is gone or the file changed
    let live = true;
    const reader = new FileReader();
    reader.onload = () => live && typeof reader.result === "string" && setUrl(reader.result);
    reader.readAsDataURL(file);
    return () => {
      live = false;
      reader.abort();
    };
  }, [file]);
  const geo = (file as GeoFile).geo;
  return (
    <span className="relative inline-flex" title={`${file.name} – sent with the next submission${geo ? ` · location ${geo.lat.toFixed(5)}, ${geo.lng.toFixed(5)}` : ""}`}>
      <span className="flex size-10 items-center justify-center overflow-hidden rounded-md border-2 border-dashed border-primary/50 bg-primary-soft/40">
        {/* eslint-disable-next-line @next/next/no-img-element -- local preview of the chosen photo (blob URL) */}
        {url ? <img src={url} alt="" className="size-full object-cover" /> : <FileText className="size-4 text-primary" aria-hidden />}
      </span>
      {geo && (
        <span className="absolute -bottom-1 -left-1 flex size-4 items-center justify-center rounded-full bg-good text-white ring-2 ring-card" aria-hidden>
          <MapPin className="size-2.5" />
        </span>
      )}
      <button
        type="button"
        disabled={disabled}
        onClick={onRemove}
        className="absolute -right-1.5 -top-1.5 flex size-4 items-center justify-center rounded-full bg-critical text-white ring-2 ring-card disabled:opacity-50"
        aria-label={`Remove ${file.name}`}
      >
        <X className="size-2.5" />
      </button>
    </span>
  );
}

/** Saved + waiting proof of one GP as one row of chips. */
export function FrtProofChips({ saved, draft, onRemove, disabled }: { saved: TicketProofFile[]; draft: File[]; onRemove: (index: number) => void; disabled: boolean }) {
  if (!saved.length && !draft.length) return null;
  return (
    <span className="flex flex-wrap items-center gap-2">
      {saved.map((f) => (
        <SavedChip key={f.id} f={f} />
      ))}
      {draft.map((f, i) => (
        <DraftChip key={`${f.name}-${i}`} file={f} disabled={disabled} onRemove={() => onRemove(i)} />
      ))}
    </span>
  );
}

/** Where the FRT's report of a GP is: with the FE, returned, verified, in a Non-Doable case, or not sent yet. */
export function FrtCheckBadge({ g, onOpenNd }: { g: TicketTaskGp; onOpenNd?: (caseId: number) => void }) {
  const pill = "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[0.71875rem] font-semibold";
  if (g.ndCase?.open && onOpenNd) {
    // the case in a popup on this page: optional E1 / E2 while the FRT may still fill them
    const fill = g.ndCase.status === "PENDING_FE" || g.ndCase.status === "FRT_PROPOSED";
    const nd = g.ndCase;
    return (
      <button type="button" onClick={() => onOpenNd(nd.id)} className={cn(pill, "bg-warning-soft text-warning-text hover:underline")} title={`${nd.label} – ${fill ? "fill E1 / E2 (optional)" : "view the case"}`}>
        {nd.ref} · {fill ? "Fill E1 / E2" : "View case"} →
      </button>
    );
  }
  if (g.ndCase?.open)
    return (
      // opens the case (with the FE; the FRT may add optional E1 / E2 until the FE fills them)
      <Link href={`/dashboard/tickets/non-doable?case=${g.ndCase.id}`} className={cn(pill, "bg-warning-soft text-warning-text hover:underline")} title={`${g.ndCase.label} – open the case`}>
        {g.ndCase.ref} · Open case →
      </Link>
    );
  if (g.frtStage === "PENDING_FE")
    return (
      <span className={cn(pill, "bg-warning-soft text-warning-text")}>
        <Clock className="size-3" aria-hidden /> Pending FE check
      </span>
    );
  if (g.frtStage === "RETURNED_FRT")
    return (
      <span className="flex flex-col items-start gap-0.5">
        <span className={cn(pill, "bg-critical-soft text-critical-text")}>
          <Undo2 className="size-3" aria-hidden /> Returned to you
        </span>
        {g.frtCheck?.remark && <span className="max-w-[14rem] text-[0.6875rem] text-critical-text">Reason: {g.frtCheck.remark}</span>}
      </span>
    );
  if (g.frtStage === "FE_VERIFIED")
    return (
      <span className={cn(pill, "bg-good-soft text-good-text")}>
        <CheckCircle2 className="size-3" aria-hidden /> Verified by FE
      </span>
    );
  return <span className="text-[0.75rem] text-muted-foreground">Not sent yet</span>;
}

/** FRT summary: their GPs and where they are. */
export function FrtSummary({ gps }: { gps: TicketTaskGp[] }) {
  const n = (p: (g: TicketTaskGp) => boolean) => gps.filter(p).length;
  const cards: [string, number, string | undefined][] = [
    ["Your GPs", gps.length, undefined],
    ["Filled", n((g) => !!g.gpCategory), "text-[var(--series-1)]"],
    ["Pending FE check", n((g) => g.frtStage === "PENDING_FE"), "text-warning-text"],
    ["Returned to you", n((g) => g.frtStage === "RETURNED_FRT"), "text-critical-text"],
    ["Verified by FE", n((g) => g.frtStage === "FE_VERIFIED"), "text-good-text"],
    ["Not filled", n((g) => !g.gpCategory), "text-muted-foreground"],
  ];
  return (
    <div className="grid grid-cols-2 gap-3 border-b border-border px-5 py-3 sm:grid-cols-3 lg:grid-cols-6">
      {cards.map(([label, value, cls]) => (
        <div key={label} className="rounded-lg border border-border px-3 py-2">
          <p className="text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">{label}</p>
          <p className={cn("tabular text-xl font-bold", value ? cls : "text-muted-foreground")}>{value}</p>
        </div>
      ))}
    </div>
  );
}

/** 3-step guide; the full text opens on demand. */
export function FrtSteps({ fes, camera }: { fes: string[]; camera: boolean }) {
  const step = "inline-flex items-center gap-1.5";
  const num = "flex size-5 items-center justify-center rounded-full bg-primary text-[0.6875rem] font-bold text-primary-foreground";
  return (
    <details className="group border-b border-border bg-primary-soft/40 px-5 py-2.5 text-[0.8125rem]">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-1.5 [&::-webkit-details-marker]:hidden">
        <span className={step}>
          <span className={num}>1</span> Choose the status
        </span>
        <span className="text-muted-foreground">→</span>
        <span className={step}>
          <span className={num}>2</span> Remark + {camera ? "Camera photo" : "photo"}
        </span>
        <span className="text-muted-foreground">→</span>
        <span className={step}>
          <span className={num}>3</span> Submit – your FE checks it
        </span>
        <span className="ml-auto inline-flex items-center gap-1 text-[0.75rem] font-medium text-primary">
          <Info className="size-3.5" aria-hidden /> <span className="group-open:hidden">Full instructions</span>
          <span className="hidden group-open:inline">Hide</span>
        </span>
      </summary>
      <p className="mt-2 text-muted-foreground">
        Choose <b>Rectification Done</b>, <b>Revisit Required</b> or <b>Non-Doable – Proposed</b> for each GP with a remark and a photo – on a phone take it with
        the <b>Camera</b> (its location, date and time are saved with it – allow camera and location), on a laptop use <b>Upload photo</b> (JPG / PNG) – then{" "}
        <b>Submit Daily Progress</b>. Your FE{fes.length ? ` (${fes.join(", ")})` : ""} checks it and sends it to the Area Manager, or returns it to you with the reason.
        Non-Doable opens a case that goes straight to your FE with the Daily Progress – the FE fills E1 / E2 and sends it to the Area Manager. You may add
        E1 / E2 yourself (optional) from Non-Doable Cases until your FE starts filling them.
      </p>
    </details>
  );
}
