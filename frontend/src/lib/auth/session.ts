import { IS_LIVE } from "@/lib/api";
import { request } from "@/lib/api/http-client";
import type { Role } from "@/types";
import { clearSessionCookie, demoLogin, readSessionCookie, writeSessionCookie } from "./demo-auth";

/**
 * Session API used by the UI. In live mode the backend owns authentication
 * (httpOnly session cookie + CSRF token); in mock mode the demo cookie is used.
 */
export interface SessionUser {
  id?: number;
  email: string;
  name: string;
  role: Role;
}

export const SESSION_COOKIE_NAME = IS_LIVE ? "pratap_session" : "pratap_demo_session";

export async function signIn(email: string, password: string, remember: boolean): Promise<SessionUser> {
  if (IS_LIVE) {
    const res = await request<{ user: SessionUser }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: email.trim(), password, remember }),
    });
    return res.user;
  }
  const s = await demoLogin(email, password);
  writeSessionCookie(s, remember);
  return s;
}

export async function fetchCurrentUser(): Promise<SessionUser | null> {
  if (!IS_LIVE) return readSessionCookie();
  try {
    return (await request<{ user: SessionUser }>("/auth/me")).user;
  } catch {
    return null;
  }
}

export async function signOut(): Promise<void> {
  if (IS_LIVE) {
    try {
      await request("/auth/logout", { method: "POST" });
    } catch {
      /* already signed out */
    }
  } else {
    clearSessionCookie();
  }
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  await request("/auth/change-password", { method: "POST", body: JSON.stringify({ currentPassword, newPassword }) });
}
