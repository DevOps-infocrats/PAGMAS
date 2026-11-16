"use client";

import { Download, FileCheck2, Loader2, ShieldCheck, Workflow } from "lucide-react";
import { useState } from "react";
import { MiniKpi } from "@/components/kpi/mini-kpi";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlays";
import { Card } from "@/components/ui/primitives";
import { ticketApi, type CohGpLists, type CohGpRow, type TicketDetail } from "@/lib/api";
import { formatCount } from "@/lib/utils/format";
import { ConfirmDialog, ticketDay, type Notice } from "./ticket-parts";

type Kind = "letter" | "amc";
const TITLE: Record<Kind, string> = { letter: "Letter Submitted Done", amc: "AMC Converted" };

/**
 * COH on User Tickets (backend: app/tickets/coh.py): the Letter Submitted Done and AMC Converted KPIs of the GPs the
 * SME forwarded to them; a click opens the GP list (date, Area Manager, FE, Target Date) with its Excel download.
 */
export function CohKpis({ data, loading }: { data?: CohGpLists; loading: boolean }) {
  const [open, setOpen] = useState<Kind | null>(null);
  // tiles only (no grid): they sit in the same row as the ticket KPIs of User Tickets
  return (
    <>
      <MiniKpi
          loading={loading}
          icon={FileCheck2}
          tone="var(--series-7)"
          label="Letter Submitted Done"
          info="GPs forwarded to you whose letter submission you recorded (also those converted to AMC afterwards). Click for the list."
          value={formatCount(data?.letterSubmitted)}
          unit="GPs"
          caption="Click to see the GP list"
          onClick={() => setOpen("letter")}
          active={open === "letter"}
        />
        <MiniKpi
          loading={loading}
          icon={Workflow}
          tone="var(--good)"
          label="AMC Converted"
          info="GPs forwarded to you whose AMC conversion you recorded. Click for the list."
          value={formatCount(data?.amcConverted)}
          unit="GPs"
          caption="Click to see the GP list"
          onClick={() => setOpen("amc")}
          active={open === "amc"}
        />
      <Dialog open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="top-[4vh] flex max-h-[92vh] max-w-6xl flex-col">{open && data && <CohGpList kind={open} rows={open === "letter" ? data.letter : data.amc} />}</DialogContent>
      </Dialog>
    </>
  );
}

function CohGpList({ kind, rows }: { kind: Kind; rows: CohGpRow[] }) {
  const cols = ["S.No.", "Ticket", "GP Code", "GP Name", "Block", "Area Manager", "FE Name", "Target Date", ...(kind === "amc" ? ["Letter Submitted Date"] : []), kind === "letter" ? "Letter Submitted Date" : "AMC Converted Date"];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 p-5">
      <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 pr-8">
        <div>
          <DialogTitle className="text-lg font-bold">{TITLE[kind]} – GP list</DialogTitle>
          <DialogDescription className="text-[0.8125rem] text-muted-foreground">
            {rows.length} GP{rows.length === 1 ? "" : "s"} · Target Date = the GP&apos;s Planned Date in the AMC plan (* = no Planned Date, the ticket week&apos;s last day).
          </DialogDescription>
        </div>
        <Button asChild size="sm" variant="outline">
          <a href={ticketApi.cohGpsXlsxUrl(kind)} download>
            <Download /> Download Excel
          </a>
        </Button>
      </div>
      <div className="min-h-[10rem] flex-1 overflow-auto rounded-lg border border-border">
        <table className="w-full min-w-[60rem] text-[0.8125rem]">
          <thead className="sticky top-0 bg-muted">
            <tr className="border-b border-border text-left text-[0.6875rem] font-semibold uppercase tracking-wide text-muted-foreground">
              {cols.map((c) => (
                <th key={c} scope="col" className="px-3 py-2">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.ticketId}:${r.gpCode}`} className="border-b border-border/60 last:border-0">
                <td className="px-3 py-1.5 text-muted-foreground">{i + 1}</td>
                <td className="whitespace-nowrap px-3 py-1.5">{r.ticket}</td>
                <td className="px-3 py-1.5 font-semibold">{r.gpCode}</td>
                <td className="min-w-[10rem] px-3 py-1.5">{r.gpName}</td>
                <td className="px-3 py-1.5 text-muted-foreground">{r.block ?? "—"}</td>
                <td className="px-3 py-1.5">{r.areaManager ?? "—"}</td>
                <td className="px-3 py-1.5">{r.fieldEngineer ?? <span className="text-warning-text">Not mapped</span>}</td>
                <td className="whitespace-nowrap px-3 py-1.5" title={r.targetFromWeek ? "No Planned Date – the ticket week's last day" : "Planned Date (AMC plan)"}>
                  {ticketDay(r.targetDate)}
                  {r.targetFromWeek && " *"}
                </td>
                {kind === "amc" && <td className="whitespace-nowrap px-3 py-1.5">{r.letterDate ? ticketDay(r.letterDate) : "—"}</td>}
                <td className="whitespace-nowrap px-3 py-1.5 font-semibold">{ticketDay((kind === "letter" ? r.letterDate : r.amcDate) ?? r.targetDate)}</td>
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td colSpan={cols.length} className="px-3 py-8 text-center text-muted-foreground">
                  {kind === "letter" ? "No letter submission recorded yet." : "No AMC conversion recorded yet."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** COH: close the GP-wise task ticket once every GP is finished (the button says why it is not possible yet). */
export function CohCloseCard({ t, onChanged }: { t: TicketDetail; onChanged: (next: TicketDetail, notice: Notice) => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (t.status === "CLOSED" || (!t.can.cohClose && !t.can.cohCloseBlock)) return null;
  const close = async (comment: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = await ticketApi.cohClose(t.id, comment);
      setOpen(false);
      onChanged(next, { ok: true, text: `${t.code} is closed. Everyone on the ticket has been notified.` });
    } catch (e) {
      setOpen(false);
      setError(e instanceof Error ? e.message : "Could not close the ticket");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-base font-bold text-subheading">Close the ticket (COH)</h3>
          <p className="text-[0.8125rem] text-muted-foreground">
            {t.can.cohClose ? "Every GP of this ticket is finished – you can close it." : t.can.cohCloseBlock}
          </p>
        </div>
        <Button variant="primary" onClick={() => setOpen(true)} disabled={busy || !t.can.cohClose} title={t.can.cohClose ? undefined : (t.can.cohCloseBlock ?? undefined)}>
          {busy ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Close Ticket
        </Button>
      </div>
      {error && (
        <p role="alert" className="mt-3 rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical-text">
          {error}
        </p>
      )}
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Close ${t.code}?`}
        description="Every GP is finished. The ticket becomes read-only; all reports, remarks and proof are kept, and everyone on the ticket sees it as Closed."
        confirmLabel="Close Ticket"
        busy={busy}
        onConfirm={(c) => void close(c)}
        comment={{ label: "Comment (optional)", placeholder: "e.g. All letters submitted and AMC converted.", required: false }}
      />
    </Card>
  );
}
