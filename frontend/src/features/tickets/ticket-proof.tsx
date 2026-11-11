"use client";

import { Download, Eye, FileText } from "lucide-react";
import { ticketApi, type GpStatus, type TicketProofFile } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { fileSize, ticketTime } from "./ticket-parts";

/** File types a GP proof document may have (same rule as the backend: app/tickets/files.py). */
export const PROOF_ACCEPT = ".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png";

/** Done (green) / Pending (orange) badge of a GP. */
export function GpStatusBadge({ status }: { status: GpStatus }) {
  return (
    <span className={cn("inline-flex rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold", status === "DONE" ? "bg-good-soft text-good-text" : "bg-warning-soft text-warning-text")}>
      {status === "DONE" ? "Done" : "Pending"}
    </span>
  );
}

/**
 * Proof documents of a GP: name + upload date, Preview (PDF / images) and Download. `compact` = one line per file
 * (tables); nothing uploaded -> `emptyText`.
 */
export function ProofList({ files, compact, emptyText = "Proof Not Uploaded" }: { files: TicketProofFile[]; compact?: boolean; emptyText?: string }) {
  if (!files.length) return <span className="text-[0.75rem] font-medium text-warning-text">{emptyText}</span>;
  return (
    <ul className={cn(compact ? "space-y-0.5" : "space-y-1.5")}>
      {files.map((f) => (
        <li key={f.id} className="flex min-w-0 items-center gap-1.5 text-[0.75rem]">
          <FileText className="size-3.5 shrink-0 text-primary" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium" title={f.fileName}>
              {f.fileName}
            </span>
            {!compact && (
              <span className="block text-[0.6875rem] text-muted-foreground">
                {fileSize(f.size)} · {ticketTime(f.uploadedAt)}
                {f.ticket ? ` · ${f.ticket}` : ""}
              </span>
            )}
          </span>
          {f.previewable && (
            <a href={ticketApi.progressFileUrl(f.id, true)} target="_blank" rel="noopener noreferrer" className="rounded p-1 text-primary hover:bg-primary-soft" title={`Preview ${f.fileName}`} aria-label={`Preview ${f.fileName}`}>
              <Eye className="size-3.5" />
            </a>
          )}
          <a href={ticketApi.progressFileUrl(f.id)} download={f.fileName} className="rounded p-1 text-primary hover:bg-primary-soft" title={`Download ${f.fileName} (uploaded ${ticketTime(f.uploadedAt)})`} aria-label={`Download ${f.fileName}`}>
            <Download className="size-3.5" />
          </a>
        </li>
      ))}
    </ul>
  );
}
