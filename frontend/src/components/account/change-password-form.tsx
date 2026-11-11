"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/primitives";
import { changePassword } from "@/lib/auth/session";
import { cn } from "@/lib/utils/cn";

export const PASSWORD_RULE = "At least 12 characters with 3 of: lower-case, upper-case, digits, symbols.";

/** Change your own password (any signed-in user): current password + new password twice. Used on Settings and in the
 *  profile menu. The server checks the current password, the strength rule and signs out other sessions. */
export function ChangePasswordForm({ onDone }: { onDone?: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  return (
    <form
      className="space-y-3"
      onSubmit={async (e) => {
        e.preventDefault();
        setMsg(null);
        if (next !== confirm) return setMsg({ ok: false, text: "New passwords do not match." });
        setBusy(true);
        try {
          await changePassword(current, next);
          setMsg({ ok: true, text: "Password changed. Other sessions were signed out." });
          setCurrent("");
          setNext("");
          setConfirm("");
          onDone?.();
        } catch (err) {
          setMsg({ ok: false, text: err instanceof Error ? err.message : "Could not change password" });
        } finally {
          setBusy(false);
        }
      }}
    >
      <Field id="pw-current" label="Current password" value={current} onChange={setCurrent} autoComplete="current-password" />
      <Field id="pw-new" label="New password" value={next} onChange={setNext} autoComplete="new-password" />
      <Field id="pw-confirm" label="Repeat new password" value={confirm} onChange={setConfirm} autoComplete="new-password" />
      {msg && <p className={cn("text-sm", msg.ok ? "text-good-text" : "text-critical-text")}>{msg.text}</p>}
      <Button type="submit" variant="primary" disabled={busy || !current || !next}>
        {busy && <Loader2 className="animate-spin" />} Update password
      </Button>
    </form>
  );
}

function Field({ id, label, value, onChange, autoComplete }: { id: string; label: string; value: string; onChange: (v: string) => void; autoComplete: string }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} type="password" value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete} maxLength={128} />
    </div>
  );
}
