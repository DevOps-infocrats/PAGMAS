import { createHash, timingSafeEqual } from "node:crypto";
import { NextResponse } from "next/server";

/**
 * Demo-mode sign-in (NEXT_PUBLIC_API_MODE=mock only). Demo accounts live in the server-only
 * env var DEMO_USERS (frontend/.env.local), never in the browser bundle:
 *   DEMO_USERS=[{"email":"admin@demo.local","password":"…","name":"Demo Admin","role":"admin"}]
 * In live mode this route does not exist – the FastAPI backend owns authentication.
 */
interface DemoUser {
  email: string;
  password: string;
  name: string;
  role: "admin" | "viewer";
}

function demoUsers(): DemoUser[] {
  try {
    const parsed: unknown = JSON.parse(process.env.DEMO_USERS ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (u): u is DemoUser =>
        typeof u?.email === "string" && typeof u?.password === "string" && u.password.length >= 8 && typeof u?.name === "string" && (u?.role === "admin" || u?.role === "viewer"),
    );
  } catch {
    return [];
  }
}

const digest = (s: string) => createHash("sha256").update(s, "utf8").digest();

export async function POST(request: Request) {
  if (process.env.NEXT_PUBLIC_API_MODE !== "mock") return new NextResponse(null, { status: 404 });
  let body: { email?: unknown; password?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid request" }, { status: 400 });
  }
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body.password === "string" ? body.password : "";
  // Uniform delay + constant-time comparison: no hint whether the e-mail exists.
  await new Promise((r) => setTimeout(r, 400));
  const users = demoUsers();
  const user = users.find((u) => u.email.toLowerCase() === email);
  const ok = timingSafeEqual(digest(password), digest(user?.password ?? "\u0000invalid")) && !!user;
  if (!users.length) return NextResponse.json({ detail: "No demo accounts configured (DEMO_USERS in frontend/.env.local)." }, { status: 503 });
  if (!ok || !user) return NextResponse.json({ detail: "The email or password doesn't match a demo account." }, { status: 401 });
  return NextResponse.json({ email: user.email, name: user.name, role: user.role });
}
