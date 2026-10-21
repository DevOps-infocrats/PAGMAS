"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { fetchCurrentUser, signOut, type SessionUser } from "@/lib/auth/session";

interface SessionContextValue {
  session: SessionUser | null;
  loading: boolean;
  isAdmin: boolean;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchCurrentUser().then((u) => {
      if (cancelled) return;
      setSession(u);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const logout = useCallback(async () => {
    await signOut();
    // Full navigation drops the client router cache so no protected data survives.
    window.location.replace(`${window.location.origin}/login`);
  }, []);

  const value = useMemo(() => ({ session, loading, isAdmin: session?.role === "admin", logout }), [session, loading, logout]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("SessionProvider missing");
  return ctx;
}
