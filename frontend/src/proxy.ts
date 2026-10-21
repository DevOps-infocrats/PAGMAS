import { NextResponse, type NextRequest } from "next/server";
import { ADMIN_PATHS, SESSION_COOKIE as DEMO_COOKIE, decodeSession } from "@/lib/auth/demo-auth";

const LIVE = process.env.NEXT_PUBLIC_API_MODE !== "mock";
const LIVE_COOKIE = "pratap_session";

/**
 * Route gate for a smoother UX. It is NOT the security boundary: in live mode
 * the backend validates the signed session and the role on every API call.
 */
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasSession = LIVE ? Boolean(request.cookies.get(LIVE_COOKIE)?.value) : Boolean(decodeSession(request.cookies.get(DEMO_COOKIE)?.value));

  if (pathname === "/") {
    return NextResponse.redirect(new URL(hasSession ? "/dashboard" : "/login", request.url));
  }

  if (pathname.startsWith("/dashboard")) {
    if (!hasSession) {
      const url = new URL("/login", request.url);
      url.searchParams.set("next", pathname + search);
      return NextResponse.redirect(url);
    }
    // Demo mode only: the demo cookie carries the role. Live roles are enforced by the API.
    if (!LIVE) {
      const demo = decodeSession(request.cookies.get(DEMO_COOKIE)?.value);
      if (demo?.role !== "admin" && ADMIN_PATHS.some((p) => pathname.startsWith(p))) {
        const url = new URL("/dashboard", request.url);
        url.searchParams.set("denied", "1");
        return NextResponse.redirect(url);
      }
    }
  }

  if (pathname === "/login" && hasSession && !LIVE) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/", "/login", "/dashboard/:path*"],
};
