import type { NextConfig } from "next";

// Server-side only: where the FastAPI backend listens. The browser never talks
// to it directly – /api/* is proxied so cookies stay first-party.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8010";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'" },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  experimental: {
    // Bodies proxied to the backend (/api rewrite) are cut at 10 MB by default. Uploads are larger: master workbook
    // up to UPLOAD_MAX_MB (60) and ticket work submissions up to TICKET_UPLOAD_MAX_MB (50). The backend still
    // enforces its own, stricter limit per path.
    proxyClientMaxBodySize: "62mb",
  },
  turbopack: {
    root: __dirname,
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async redirects() {
    // Short addresses people type or bookmark – the ticket pages live under /dashboard/tickets/…
    return [
      { source: "/dashboard/user", destination: "/dashboard/tickets/user", permanent: false },
      { source: "/dashboard/tickets", destination: "/dashboard/tickets/user", permanent: false },
      { source: "/dashboard/admin", destination: "/dashboard/tickets/admin", permanent: false },
    ];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
