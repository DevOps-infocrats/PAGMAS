import type { Role } from "@/types";

/**
 * DEMO AUTHENTICATION ONLY (Phase 1).
 * - Demo accounts are configured server-side (DEMO_USERS in frontend/.env.local) and
 *   checked by the /demo-auth route – no password is shipped to the browser.
 * - The session is an unsigned cookie readable by the browser. It is NOT secure
 *   and must be replaced by backend-issued, httpOnly, signed sessions/JWTs with
 *   server-side authorization in Phase 2.
 */
export const SESSION_COOKIE = "pratap_demo_session";

export interface DemoSession {
  email: string;
  name: string;
  role: Role;
}

export function encodeSession(s: DemoSession): string {
  return encodeURIComponent(btoa(JSON.stringify(s)));
}

export function decodeSession(raw: string | undefined | null): DemoSession | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(atob(decodeURIComponent(raw))) as Partial<DemoSession>;
    if (typeof parsed.email !== "string" || typeof parsed.name !== "string") return null;
    if (parsed.role !== "admin" && parsed.role !== "viewer") return null;
    return { email: parsed.email, name: parsed.name, role: parsed.role };
  } catch {
    return null;
  }
}

export async function demoLogin(email: string, password: string): Promise<DemoSession> {
  const res = await fetch("/demo-auth", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  const body = (await res.json().catch(() => ({}))) as Partial<DemoSession> & { detail?: string };
  if (!res.ok) throw new Error(body.detail ?? "Demo sign-in failed.");
  const session = decodeSession(encodeSession(body as DemoSession));
  if (!session) throw new Error("Demo sign-in failed.");
  return session;
}

export function writeSessionCookie(s: DemoSession, remember: boolean) {
  const maxAge = remember ? `; max-age=${60 * 60 * 24 * 7}` : "";
  document.cookie = `${SESSION_COOKIE}=${encodeSession(s)}; path=/; samesite=lax${maxAge}`;
}

export function clearSessionCookie() {
  document.cookie = `${SESSION_COOKIE}=; path=/; max-age=0; samesite=lax`;
}

export function readSessionCookie(): DemoSession | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${SESSION_COOKIE}=`));
  return decodeSession(match?.slice(SESSION_COOKIE.length + 1));
}

export const ADMIN_PATHS = ["/dashboard/operations", "/dashboard/settings", "/dashboard/users", "/dashboard/mail"];
