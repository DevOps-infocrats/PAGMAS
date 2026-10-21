import type { Metadata } from "next";
import { Suspense } from "react";
import { Logo } from "@/components/brand/logo";
import { ClientGate } from "@/components/layout/client-gate";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.05fr_1fr]">
      <BrandPanel />
      <div className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo variant="wordmark" width={132} eager />
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
          <p className="mt-1 text-sm text-muted-foreground">Fibre network operations &amp; analytics</p>
          <ClientGate fallback={<div className="mt-8 h-72 animate-pulse rounded-lg bg-muted" />}>
            <Suspense fallback={<div className="mt-8 h-72 animate-pulse rounded-lg bg-muted" />}>
              <LoginForm />
            </Suspense>
          </ClientGate>
        </div>
      </div>
    </div>
  );
}

function BrandPanel() {
  return (
    <div className="relative hidden overflow-hidden border-r border-border bg-card lg:flex lg:flex-col lg:justify-between lg:p-12">
      <Logo variant="full" width={180} eager className="-ml-4 -mt-10" />
      <FibreIllustration />
      <div className="relative z-10 max-w-md space-y-3">
        <p className="text-3xl font-semibold leading-tight tracking-tight">
          One clear view of every circle, block and Gram Panchayat.
        </p>
        <p className="text-sm text-muted-foreground">
          HOTO progress, AMC coverage, availability and fibre route — in a single operations workspace.
        </p>
      </div>
    </div>
  );
}

/** Decorative fibre routes in the brand gradient (purely illustrative). */
function FibreIllustration() {
  const paths = [
    "M-20 300 C 120 240, 220 360, 360 290 S 560 210, 720 260",
    "M-20 360 C 140 320, 260 420, 400 350 S 600 300, 720 340",
    "M-20 240 C 100 180, 240 280, 380 220 S 580 140, 720 180",
  ];
  return (
    <svg className="pointer-events-none absolute inset-x-0 top-1/2 h-[420px] w-full -translate-y-1/2 opacity-80" viewBox="0 0 700 520" preserveAspectRatio="none" aria-hidden>
      <defs>
        <linearGradient id="fibre" x1="0" x2="1">
          <stop offset="0" stopColor="var(--brand-green)" />
          <stop offset="1" stopColor="var(--brand-blue)" />
        </linearGradient>
      </defs>
      {paths.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="url(#fibre)" strokeWidth={i === 1 ? 2 : 1.25} strokeOpacity={i === 1 ? 0.9 : 0.35} />
      ))}
      {[
        [120, 262],
        [360, 290],
        [400, 350],
        [580, 152],
      ].map(([cx, cy], i) => (
        <g key={i}>
          <circle cx={cx} cy={cy} r={9} fill="var(--brand-blue)" fillOpacity={0.12} />
          <circle cx={cx} cy={cy} r={3.5} fill="var(--card)" stroke="url(#fibre)" strokeWidth={2} />
        </g>
      ))}
    </svg>
  );
}
