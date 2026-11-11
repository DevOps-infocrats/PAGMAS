"use client";

import { Loader2, Send, Share2 } from "lucide-react";
import { useState } from "react";
import { ErrorState, TableSkeleton } from "@/components/feedback/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { useApiQuery } from "@/hooks/use-api-query";
import { ticketApi, type SharePerson, type TicketDetail } from "@/lib/api";
import { cn } from "@/lib/utils/cn";
import { TEXTAREA, type Notice } from "./ticket-parts";

type Pick = { role: "CBH" | "SME"; name: string; email: string };
const key = (p: Pick) => `${p.role}|${p.email}`;

/**
 * Area Manager -> CBH / SME of the ticket's circle (Escalation Matrix only): the latest GP sheet (status, remarks,
 * proof of every GP) and the AM's remark go by e-mail; people with a dashboard account also see the ticket read-only.
 * Every share is recorded in the ticket's activity (backend: service.share).
 */
export function ShareCard({ t, onChanged }: { t: TicketDetail; onChanged: (next: TicketDetail, n: Notice) => void }) {
  const [open, setOpen] = useState(false);
  const contacts = useApiQuery(open ? `share-contacts:${t.id}` : null, () => ticketApi.getShareContacts(t.id));
  const [picked, setPicked] = useState<Pick[]>([]);
  const [remark, setRemark] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shares = t.events.filter((e) => e.action === "SHARED").length;

  const toggle = (p: Pick) => setPicked((cur) => (cur.some((x) => key(x) === key(p)) ? cur.filter((x) => key(x) !== key(p)) : [...cur, p]));
  const send = async () => {
    if (!picked.length) return setError("Select at least one CBH or SME");
    if (remark.trim().length < 3) return setError("Write a remark (at least 3 characters)");
    setBusy(true);
    setError(null);
    try {
      const next = await ticketApi.share(t.id, picked, remark.trim());
      onChanged(next, { ok: true, text: `Shared with ${picked.map((p) => `${p.role} ${p.name}`).join(", ")} – the latest GP sheet and your remark are being e-mailed.` });
      setPicked([]);
      setRemark("");
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The ticket could not be shared");
    } finally {
      setBusy(false);
    }
  };

  const group = (role: "CBH" | "SME", people: SharePerson[]) => (
    <div className="min-w-0 space-y-1.5">
      <p className="text-[0.75rem] font-semibold uppercase tracking-wide text-muted-foreground">{role}</p>
      {people.length === 0 ? (
        <p className="text-[0.78125rem] text-muted-foreground">No {role} with an e-mail in the Escalation Matrix for {t.circle}.</p>
      ) : (
        people.flatMap((p) =>
          p.emails.map((e) => {
            const item = { role, name: p.name, email: e.email };
            const on = picked.some((x) => key(x) === key(item));
            return (
              <label key={key(item)} className={cn("flex cursor-pointer items-start gap-2 rounded-md border px-2.5 py-1.5 text-[0.78125rem]", on ? "border-primary bg-primary-soft/40" : "border-border")}>
                <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={on} disabled={busy} onChange={() => toggle(item)} />
                <span className="min-w-0">
                  <b className="font-semibold">{p.name}</b> <span className="text-muted-foreground">· {e.email}</span>
                  <span className="block text-[0.6875rem] text-muted-foreground">
                    {e.account ? "Dashboard account – also sees the ticket (view only)" : "E-mail only"}
                    {e.onTicket && " · already on this ticket"}
                  </span>
                </span>
              </label>
            );
          }),
        )
      )}
    </div>
  );

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
        <div>
          <h3 className="flex items-center gap-2 text-base font-bold text-subheading">
            <Share2 className="size-4 text-primary" aria-hidden /> Inform CBH / SME
          </h3>
          <p className="text-[0.78125rem] text-muted-foreground">
            Send the latest GP sheet (status, remarks and proof of every GP) with your remark to the CBH / SME of {t.circle ?? "the circle"}
            {shares > 0 && ` · shared ${shares} time${shares === 1 ? "" : "s"} – see Activity`}
          </p>
        </div>
        <Button size="sm" variant={open ? "ghost" : "outline"} onClick={() => setOpen((o) => !o)} disabled={busy}>
          {open ? "Cancel" : (
            <>
              <Share2 /> Share with CBH / SME
            </>
          )}
        </Button>
      </div>
      {open && (
        <div className="space-y-3 border-t border-border px-5 py-4">
          {contacts.error ? (
            <ErrorState error={contacts.error} onRetry={contacts.reload} className="py-4" />
          ) : !contacts.data ? (
            <TableSkeleton rows={3} />
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {group("CBH", contacts.data.cbh)}
              {group("SME", contacts.data.sme)}
            </div>
          )}
          <label className="block space-y-1">
            <span className="text-[0.8125rem] font-medium">
              Remark <span className="text-critical-text">*</span>
            </span>
            <textarea value={remark} onChange={(e) => setRemark(e.target.value)} rows={3} maxLength={2000} disabled={busy} className={TEXTAREA} placeholder="e.g. 12 GPs ready for letter submission, 3 need a revisit – please support with …" />
          </label>
          {error && <p className="text-xs text-critical-text">{error}</p>}
          <div className="flex items-center justify-end gap-2">
            <span className="text-xs text-muted-foreground">{picked.length ? `${picked.length} selected` : "Select the CBH / SME"}</span>
            <Button variant="primary" onClick={() => void send()} disabled={busy || !picked.length}>
              {busy ? <Loader2 className="animate-spin" /> : <Send />} Send
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
