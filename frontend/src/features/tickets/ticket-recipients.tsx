"use client";

import { Loader2, Mail, RefreshCw, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { ticketApi, type TicketDetail, type TicketRecipient } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { ticketTime, type Notice } from "./ticket-parts";

export const ROLE_LABEL: Record<TicketRecipient["role"], string> = { CBH: "CBH", SME: "SME", COH: "COH", AM: "Area Manager", FE: "Field Engineer", USER: "Dashboard user", OTHER: "Other recipient" };

const MAIL_META: Record<TicketRecipient["emailStatus"], { label: string; cls: string }> = {
  NONE: { label: "Not e-mailed", cls: "text-muted-foreground" },
  PENDING: { label: "Sending…", cls: "text-[var(--series-7)]" },
  SENT: { label: "E-mail sent", cls: "text-good-text" },
  FAILED: { label: "E-mail failed", cls: "text-critical-text" },
};

/**
 * People a generated ticket was sent to (CBH / SME / Area Manager / other user), whether they see it on the dashboard
 * or got the e-mail only, and – for admins – the e-mail result with Send / Retry (the ticket itself never changes).
 */
export function RecipientsCard({ t, onNotice }: { t: TicketDetail; onNotice?: (n: Notice) => void }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  // e-mails go out in the background: newer recipient states fetched while one is still "Sending…"
  const [fresh, setFresh] = useState<{ ticket: number; rows: TicketRecipient[]; polls: number } | null>(null);
  const rows = fresh && fresh.ticket === t.id ? fresh.rows : t.recipients;
  const polls = fresh && fresh.ticket === t.id ? fresh.polls : 0;
  const sending = rows.some((r) => r.emailStatus === "PENDING");

  useEffect(() => {
    if (!sending || polls >= 15) return;
    const timer = setTimeout(async () => {
      try {
        const next = await ticketApi.get(t.id);
        setFresh({ ticket: t.id, rows: next.recipients, polls: polls + 1 });
      } catch {
        setFresh({ ticket: t.id, rows, polls: polls + 1 });
      }
    }, 2000);
    return () => clearTimeout(timer);
  }, [sending, polls, t.id, rows]);

  if (rows.length === 0) return null;

  const send = async (r: TicketRecipient) => {
    setBusy(r.id);
    setError(null);
    try {
      const next = await ticketApi.resendEmail(t.id, r.id);
      setFresh({ ticket: t.id, rows: next.recipients, polls: 0 });
      onNotice?.({ ok: true, text: `E-mail to ${r.name} (${r.email}) is being sent – the status below updates in a moment.` });
    } catch (e) {
      setError(e instanceof Error ? e.message : "The e-mail could not be sent");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="p-5">
      <h3 className="flex items-center gap-2 text-base font-bold text-subheading">
        <Users className="size-4 text-primary" aria-hidden /> Recipients
      </h3>
      <ul className="mt-3 divide-y divide-border">
        {rows.map((r) => {
          const m = MAIL_META[r.emailStatus];
          return (
            <li key={r.id} className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-[0.84375rem] font-semibold">
                    {r.name} <span className="ml-1 rounded bg-muted px-1.5 py-0.5 text-[0.65625rem] font-semibold uppercase tracking-wide text-muted-foreground">{ROLE_LABEL[r.role]}</span>
                    {r.typed && (
                      <span className="ml-1 rounded bg-primary-soft px-1.5 py-0.5 text-[0.65625rem] font-semibold text-primary" title="Name and e-mail typed by the admin at Generate Ticket – not from the Escalation Matrix">
                        typed
                      </span>
                    )}
                  </p>
                  <p className="truncate text-[0.78125rem] text-muted-foreground">
                    {r.email}
                    {r.role === "FE" && r.areaManager && <> · AM {r.areaManager}</>}
                  </p>
                </div>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-2 py-0.5 text-[0.6875rem] font-semibold",
                    r.access === "dashboard" ? "bg-good-soft text-good-text" : "bg-warning-soft text-warning-text",
                  )}
                  title={r.access === "dashboard" ? (r.canWork ? "Sees the ticket and can work on it" : "Sees the ticket (view only)") : "No dashboard account – e-mail only"}
                >
                  {r.access === "dashboard" ? (r.canWork ? "Dashboard" : "View only") : "E-mail only"}
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 text-[0.75rem]">
                <span className={cn("flex items-center gap-1 font-medium", m.cls)}>
                  <Mail className="size-3.5" aria-hidden /> {m.label}
                  {r.emailedAt && r.emailStatus !== "NONE" && <span className="font-normal text-muted-foreground">· {ticketTime(r.emailedAt)}</span>}
                  {r.workbook && <span className="font-normal text-muted-foreground">· {r.role === "FE" ? "with Excel of their GPs only" : "with own Excel"}</span>}
                </span>
                {t.can.email && r.emailStatus !== "PENDING" && (
                  <Button size="sm" variant="ghost" className="h-7 px-2 text-[0.75rem]" disabled={busy !== null} onClick={() => send(r)}>
                    {busy === r.id ? <Loader2 className="animate-spin" /> : <RefreshCw />} {r.emailStatus === "FAILED" ? "Retry" : r.emailStatus === "SENT" ? "Resend" : "Send e-mail"}
                  </Button>
                )}
              </div>
              {t.can.email && r.emailStatus === "FAILED" && r.emailError && <p className="text-[0.71875rem] text-critical-text">{r.emailError}</p>}
            </li>
          );
        })}
      </ul>
      {error && (
        <p role="alert" className="mt-3 rounded-md border border-critical/30 bg-critical-soft px-3 py-2 text-[0.78125rem] text-critical-text">
          {error}
        </p>
      )}
    </Card>
  );
}
