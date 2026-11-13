"use client";

import { CloudUpload, FileText, Loader2, Lock, Play, Send, X } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { ticketApi, type TicketDetail } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { ConfirmDialog, TEXTAREA, fileSize, type Notice } from "./ticket-parts";

// Same rules as the backend (app/tickets/files.py); the backend checks again, including the file content.
const EXTENSIONS = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png"];
const ACCEPT = EXTENSIONS.join(",");
const MAX_FILE_MB = 20;
const MAX_TOTAL_MB = 50;
const MAX_FILES = 10;
const MIN_TEXT = 10;

const ext = (name: string) => (name.lastIndexOf(".") >= 0 ? name.slice(name.lastIndexOf(".")).toLowerCase() : "");

/**
 * Work Submission of the assigned user: start the ticket, then files + a description of the completed work and
 * "Submit for Review". Read-only while the work is under review and once the ticket is closed.
 */
export function WorkSubmission({ t, onChanged }: { t: TicketDetail; onChanged: (next: TicketDetail, notice: Notice) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [text, setText] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [touched, setTouched] = useState(false);
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  if (t.status === "PENDING_REVIEW" || t.status === "CLOSED") {
    return (
      <Card className="flex items-start gap-3 p-5">
        <Lock className="mt-0.5 size-5 shrink-0 text-muted-foreground" aria-hidden />
        <div>
          <h3 className="text-base font-bold text-subheading">Work submission</h3>
          <p className="text-sm text-muted-foreground">
            {t.status === "CLOSED"
              ? "This ticket is closed. The submitted work is read-only."
              : "Your work has been submitted and is waiting for the admin's review. It can be changed again only if the admin requests changes."}
          </p>
        </div>
      </Card>
    );
  }

  if (t.can.start) {
    return (
      <Card className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-base font-bold text-subheading">Work submission</h3>
          <p className="text-sm text-muted-foreground">Start working on the ticket to upload documents and submit your work for review.</p>
        </div>
        <Button
          variant="primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              onChanged(await ticketApi.start(t.id), { ok: true, text: `${t.code} is now In Progress.` });
            } catch (e) {
              setError(e instanceof Error ? e.message : "Could not start the ticket");
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? <Loader2 className="animate-spin" /> : <Play />} Start working
        </Button>
        {error && <p className="text-sm text-critical-text sm:basis-full">{error}</p>}
      </Card>
    );
  }

  if (!t.can.submit) return null;

  const add = (list: FileList | File[]) => {
    const next = [...files];
    const errs: string[] = [];
    for (const f of Array.from(list)) {
      if (!EXTENSIONS.includes(ext(f.name))) errs.push(`${f.name}: type not allowed (PDF, DOC, DOCX, XLS, XLSX, JPG, JPEG, PNG)`);
      else if (f.size === 0) errs.push(`${f.name}: the file is empty`);
      else if (f.size > MAX_FILE_MB * 1024 * 1024) errs.push(`${f.name}: larger than ${MAX_FILE_MB} MB`);
      else if (next.some((x) => x.name === f.name && x.size === f.size)) errs.push(`${f.name}: already added`);
      else if (next.length >= MAX_FILES) errs.push(`At most ${MAX_FILES} files per submission`);
      else next.push(f);
    }
    if (next.reduce((s, f) => s + f.size, 0) > MAX_TOTAL_MB * 1024 * 1024) {
      errs.push(`The files together must stay under ${MAX_TOTAL_MB} MB`);
      return setProblems(errs);
    }
    setFiles(next);
    setProblems(errs);
  };

  const textOk = text.trim().length >= MIN_TEXT;
  const total = files.reduce((s, f) => s + f.size, 0);

  const send = async () => {
    setBusy(true);
    setError(null);
    setProgress(files.length ? 0 : null);
    try {
      const next = await ticketApi.submit(t.id, text.trim(), files, files.length ? setProgress : undefined);
      setFiles([]);
      setText("");
      setConfirm(false);
      onChanged(next, { ok: true, text: `${t.code} was submitted for review. The admin has been notified.` });
    } catch (e) {
      setConfirm(false);
      setError(e instanceof Error ? e.message : "Submission failed");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };

  return (
    <Card className="p-5">
      <h3 className="text-base font-bold text-subheading">{t.status === "CHANGES_REQUESTED" ? "Submit revised work" : "Work submission"}</h3>
      <p className="text-[0.8125rem] text-muted-foreground">Upload your completed work documents and describe what you have done, then submit it for the admin&apos;s review.</p>

      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        {/* A. documents */}
        <div className="space-y-2">
          <p className="text-[0.8125rem] font-medium">Documents</p>
          <div
            role="button"
            tabIndex={0}
            aria-label="Upload documents: drop files here or press Enter to browse"
            onClick={() => input.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              if (!busy) add(e.dataTransfer.files);
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed px-4 py-7 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25",
              drag ? "border-primary bg-primary-soft/50" : "border-input hover:border-primary/60 hover:bg-accent/40",
              busy && "pointer-events-none opacity-60",
            )}
          >
            <CloudUpload className="size-7 text-primary" aria-hidden />
            <p className="text-sm font-medium">
              Drag &amp; drop files here, or <span className="text-primary underline underline-offset-2">browse</span>
            </p>
            <p className="text-xs text-muted-foreground">
              PDF, DOC, DOCX, XLS, XLSX, JPG, JPEG, PNG · up to {MAX_FILE_MB} MB each, {MAX_FILES} files, {MAX_TOTAL_MB} MB in total
            </p>
            <input
              ref={input}
              type="file"
              multiple
              accept={ACCEPT}
              className="sr-only"
              tabIndex={-1}
              onChange={(e) => {
                if (e.target.files) add(e.target.files);
                e.target.value = "";
              }}
            />
          </div>
          {problems.length > 0 && (
            <ul role="alert" className="space-y-0.5 text-xs text-critical-text">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          {files.length > 0 && (
            <ul className="divide-y divide-border rounded-lg border border-border">
              {files.map((f, i) => (
                <li key={`${f.name}-${f.size}`} className="flex items-center gap-3 px-3 py-2">
                  <FileText className="size-4 shrink-0 text-primary" aria-hidden />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{f.name}</span>
                    <span className="block text-xs text-muted-foreground">{fileSize(f.size)}</span>
                  </span>
                  <Button size="icon-sm" variant="ghost" aria-label={`Remove ${f.name}`} disabled={busy} onClick={() => setFiles(files.filter((_, j) => j !== i))}>
                    <X />
                  </Button>
                </li>
              ))}
              <li className="px-3 py-1.5 text-xs text-muted-foreground">
                {files.length} file{files.length === 1 ? "" : "s"} · {fileSize(total)}
              </li>
            </ul>
          )}
          {progress != null && (
            <div className="space-y-1" role="status" aria-live="polite">
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
              <p className="text-xs text-muted-foreground">{progress < 1 ? `Uploading… ${Math.round(progress * 100)}%` : "Checking the files…"}</p>
            </div>
          )}
        </div>

        {/* B. description */}
        <label className="flex flex-col gap-2">
          <span className="text-[0.8125rem] font-medium">
            Work completion description <span className="text-critical-text">*</span>
          </span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={9}
            maxLength={10000}
            disabled={busy}
            placeholder="Describe the work you have completed..."
            aria-invalid={touched && !textOk}
            className={cn(TEXTAREA, "min-h-[11.875rem] flex-1")}
          />
          <span className={cn("text-xs", touched && !textOk ? "text-critical-text" : "text-muted-foreground")}>
            {touched && !textOk ? `Explain what was done (at least ${MIN_TEXT} characters).` : `${text.trim().length} / 10,000 characters`}
          </span>
        </label>
      </div>

      {error && (
        <p role="alert" className="mt-4 rounded-md border border-critical/30 bg-critical-soft px-4 py-2.5 text-sm text-critical-text">
          {error}
        </p>
      )}

      {/* C. submit */}
      <div className="mt-4 flex justify-end">
        <Button
          variant="primary"
          size="lg"
          disabled={busy}
          onClick={() => {
            setTouched(true);
            if (textOk) setConfirm(true);
          }}
        >
          {busy ? <Loader2 className="animate-spin" /> : <Send />} Submit for Review
        </Button>
      </div>

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Submit work for review?"
        description={`${files.length ? `${files.length} file${files.length === 1 ? "" : "s"} and your description` : "Your description (no files)"} will be sent to the admin. You cannot change the submission unless the admin requests changes.`}
        confirmLabel="Submit for Review"
        busy={busy}
        onConfirm={send}
      />
    </Card>
  );
}
