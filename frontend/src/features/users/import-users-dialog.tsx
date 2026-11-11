"use client";

import { FileSpreadsheet, Loader2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { StatusBadge } from "@/components/feedback/badges";
import { Button } from "@/components/ui/button";
import { DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { adminApi, type UserImportItem, type UserImportResult } from "@/lib/api";
import { cn } from "@/lib/utils/cn";

const ACCEPT = ".xlsx,.xlsm,.xlsb,.csv";
const STATUS: Record<UserImportItem["status"], { tone: "good" | "neutral" | "warning"; label: string }> = {
  NEW: { tone: "good", label: "New" },
  CREATED: { tone: "good", label: "Created" },
  EXISTS: { tone: "neutral", label: "Already a user" },
  SKIPPED: { tone: "warning", label: "Skipped" },
};

/** Bulk import: pick an Excel / CSV file with Name and Email columns -> preview -> create the new Viewer accounts. */
export function ImportUsersDialog({ onDone }: { onDone: (msg: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<UserImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (f: File, dryRun: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await adminApi.importUsers(f, dryRun);
      if (dryRun) setResult(r);
      else onDone(`${r.created} user(s) created from ${f.name} with the temporary password ${r.temporaryPassword}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  };

  const pick = (f: File | undefined) => {
    if (!f) return;
    setFile(f);
    setResult(null);
    void run(f, true);
  };

  const createButton = (
    <Button type="button" variant="primary" disabled={!file || !result || result.new === 0 || busy} onClick={() => file && void run(file, false)}>
      {busy && result && <Loader2 className="animate-spin" />} Create {result?.new ?? 0} user{result?.new === 1 ? "" : "s"}
    </Button>
  );

  return (
    <DialogContent className="top-[4vh] flex max-h-[92vh] max-w-3xl flex-col">
      <div className="flex min-h-0 flex-1 flex-col gap-4 p-5">
        <div className="shrink-0 pr-8">
          <DialogTitle className="text-base font-bold">Import users</DialogTitle>
          <DialogDescription className="text-[0.8125rem] text-muted-foreground">
            Excel (.xlsx, .xlsm, .xlsb) or CSV file with a <b>Name</b> and an <b>Email</b> column. Every new e-mail address becomes a <b>Viewer</b> with
            the same temporary password; existing users are not changed. Areas can be added afterwards with Edit.
          </DialogDescription>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-3 rounded-lg border border-dashed border-border p-4">
          <FileSpreadsheet className="size-5 text-primary" />
          <span className="min-w-0 flex-1 truncate text-sm">{file ? file.name : "No file selected"}</span>
          <input
            ref={input}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              pick(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <Button type="button" variant="outline" onClick={() => input.current?.click()} disabled={busy}>
            <Upload /> {file ? "Choose another file" : "Choose file"}
          </Button>
        </div>

        {busy && !result && (
          <p className="flex shrink-0 items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Reading the file…
          </p>
        )}

        {result && (
          <>
            <div className="flex shrink-0 flex-wrap items-center gap-2 text-xs">
              <Count label="Rows" value={result.total} />
              <Count label="Will be created" value={result.new} tone="good" />
              <Count label="Already users" value={result.exists} />
              <Count label="Skipped" value={result.skipped} tone={result.skipped ? "warning" : undefined} />
              <span className="ml-auto">{createButton}</span>
            </div>
            {result.new > 0 && (
              <p className="shrink-0 text-[0.8125rem] text-muted-foreground">
                Temporary password for the new users: <code className="rounded bg-muted px-1.5 py-0.5 font-semibold text-foreground">{result.temporaryPassword}</code>{" "}
                – ask them to change it after signing in (account menu or Settings → Change password).
              </p>
            )}
            <div className="min-h-[8.75rem] flex-1 overflow-auto rounded-lg border border-border">
              <table className="w-full min-w-[35rem] text-sm">
                <thead className="sticky top-0 bg-card">
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    {["Row", "Name", "Email", "Result"].map((c) => (
                      <th key={c} scope="col" className="px-3 py-2 font-medium">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((it) => (
                    <tr key={`${it.row}:${it.email}`} className="border-b border-border/60 last:border-0">
                      <td className="px-3 py-1.5 text-muted-foreground">{it.row}</td>
                      <td className="px-3 py-1.5">{it.name || "—"}</td>
                      <td className="px-3 py-1.5 text-muted-foreground">{it.email || "—"}</td>
                      <td className="px-3 py-1.5">
                        <StatusBadge tone={STATUS[it.status].tone}>{STATUS[it.status].label}</StatusBadge>
                        {it.reason && it.status === "SKIPPED" && <span className="ml-2 text-xs text-warning-text">{it.reason}</span>}
                      </td>
                    </tr>
                  ))}
                  {!result.items.length && (
                    <tr>
                      <td colSpan={4} className="px-3 py-4 text-center text-muted-foreground">
                        No user rows found under the header.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}

        {error && <p className="shrink-0 text-sm text-critical-text">{error}</p>}
        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-border pt-3">
          {result && result.new === 0 && <span className="mr-auto text-xs text-muted-foreground">No new e-mail address in this file – nothing to create.</span>}
          {createButton}
        </div>
      </div>
    </DialogContent>
  );
}

function Count({ label, value, tone }: { label: string; value: number; tone?: "good" | "warning" }) {
  return (
    <span
      className={cn(
        "rounded-md border px-2.5 py-1",
        tone === "good" ? "border-good/30 bg-good-soft text-good-text" : tone === "warning" ? "border-warning/30 bg-warning-soft text-warning-text" : "border-border text-muted-foreground",
      )}
    >
      {label}: <b>{value}</b>
    </span>
  );
}
