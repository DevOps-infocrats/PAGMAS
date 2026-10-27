import type { Metadata } from "next";
import { Activity, MapPinned, ShieldCheck, Wrench } from "lucide-react";
import { Suspense } from "react";
import { Logo } from "@/components/brand/logo";
import { ClientGate } from "@/components/layout/client-gate";
import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

const HIGHLIGHTS = [
  { icon: MapPinned, title: "Circle → Block → GP", text: "Drill down from a state to a single Gram Panchayat" },
  { icon: Wrench, title: "HOTO & AMC", text: "Handover progress and AMC conversion in one place" },
  { icon: Activity, title: "Uptime", text: "Month-to-date availability and penalty-prone blocks" },
];

export default function LoginPage() {
  return (
    <div className="login-scene relative isolate flex min-h-dvh overflow-hidden text-white">
      <NetworkBackdrop />

      <div className="relative z-10 mx-auto grid w-full max-w-[1240px] items-center gap-12 px-5 py-10 sm:px-8 lg:grid-cols-[1.1fr_440px] lg:gap-16 lg:px-12">
        <section className="hidden lg:block">
          <Logo variant="full" width={170} eager className="-ml-5 -mt-6 drop-shadow-[0_6px_24px_rgb(25_189_74/0.25)]" />
          <p className="mt-6 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-[11.5px] font-semibold uppercase tracking-[0.14em] text-[#9fe3b8] backdrop-blur">
            <span className="size-1.5 rounded-full bg-[#19bd4a] shadow-[0_0_8px_#19bd4a]" aria-hidden />
            Network analytics
          </p>
          <h2 className="mt-5 max-w-xl text-[42px] font-semibold leading-[1.12] tracking-tight">
            One clear view of every{" "}
            <span className="bg-gradient-to-r from-[#3ddc74] via-[#22c3a6] to-[#38b6f0] bg-clip-text text-transparent">circle, block and Gram Panchayat.</span>
          </h2>
          <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-[#b7cad6]">
            HOTO progress, AMC coverage, availability and fibre route — in a single operations workspace.
          </p>

          <ul className="mt-9 grid max-w-xl gap-3">
            {HIGHLIGHTS.map((h) => (
              <li key={h.title} className="flex items-center gap-4 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-3 backdrop-blur-sm">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-[#19bd4a]/25 to-[#0a8fc4]/25 text-[#7fe0a6] ring-1 ring-white/10">
                  <h.icon className="size-5" aria-hidden />
                </span>
                <span>
                  <span className="block text-sm font-semibold text-white">{h.title}</span>
                  <span className="block text-[13px] text-[#a9bfcc]">{h.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="mx-auto w-full max-w-[440px]">
          <div className="login-card-in rounded-[22px] bg-gradient-to-br from-[#19bd4a] via-[#14a6a0] to-[#0a8fc4] p-[1.5px] shadow-[0_30px_80px_-20px_rgb(0_0_0/0.6),0_0_60px_-10px_rgb(10_143_196/0.45)]">
            <div className="rounded-[21px] bg-card px-7 pb-7 pt-8 text-card-foreground sm:px-9 sm:pb-9">
              <div className="flex flex-col items-center text-center">
                <span className="relative flex size-16 items-center justify-center rounded-2xl bg-gradient-to-br from-[#e9f9ef] to-[#e4f3fb] ring-1 ring-[#19bd4a]/20">
                  <span className="login-glow absolute inset-0 rounded-2xl" aria-hidden />
                  <Logo variant="mark" width={38} eager />
                </span>
                <h1 className="mt-5 text-[24px] font-semibold tracking-tight text-heading">Welcome back</h1>
                <p className="mt-1 text-sm text-muted-foreground">Sign in to Pratap Network Analytics</p>
              </div>

              <ClientGate fallback={<div className="mt-8 h-72 animate-pulse rounded-lg bg-muted" />}>
                <Suspense fallback={<div className="mt-8 h-72 animate-pulse rounded-lg bg-muted" />}>
                  <LoginForm />
                </Suspense>
              </ClientGate>

              <p className="mt-6 flex items-center justify-center gap-1.5 border-t border-border pt-5 text-xs text-subtle-foreground">
                <ShieldCheck className="size-3.5 text-[#19a84a]" aria-hidden />
                Secure, encrypted session · authorised users only
              </p>
            </div>
          </div>
          <p className="mt-6 text-center text-xs text-[#8aa3b2]">Pratap · Carving Lives</p>
        </section>
      </div>
    </div>
  );
}

/** Decorative fibre network in the logo colours: glows, dotted grid, routes with moving light pulses and nodes. */
function NetworkBackdrop() {
  const routes = [
    "M-40 520 C 160 420, 300 600, 520 470 S 860 330, 1040 420 S 1360 520, 1520 380",
    "M-40 640 C 200 560, 380 720, 620 610 S 960 500, 1180 590 S 1420 640, 1520 560",
    "M-40 380 C 140 300, 320 420, 500 330 S 820 200, 1020 260 S 1340 300, 1520 200",
    "M-40 760 C 240 700, 460 820, 700 740 S 1040 660, 1260 720 S 1440 760, 1520 700",
  ];
  const nodes = [
    [240, 470],
    [520, 470],
    [820, 370],
    [1040, 420],
    [380, 640],
    [620, 610],
    [1180, 590],
    [500, 330],
    [1020, 260],
    [700, 740],
  ];
  return (
    <div className="pointer-events-none absolute inset-0 -z-10" aria-hidden>
      <div className="login-aurora login-aurora-a" />
      <div className="login-aurora login-aurora-b" />
      <div className="login-aurora login-aurora-c" />
      <div className="login-grid absolute inset-0" />
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 1480 900" preserveAspectRatio="xMidYMid slice">
        <defs>
          <linearGradient id="route" x1="0" x2="1">
            <stop offset="0" stopColor="#19bd4a" />
            <stop offset="1" stopColor="#0a8fc4" />
          </linearGradient>
          <radialGradient id="node-glow">
            <stop offset="0" stopColor="#3ddc74" stopOpacity="0.55" />
            <stop offset="1" stopColor="#3ddc74" stopOpacity="0" />
          </radialGradient>
        </defs>
        {routes.map((d, i) => (
          <g key={i}>
            <path d={d} fill="none" stroke="url(#route)" strokeWidth={1.2} strokeOpacity={0.28} />
            <path d={d} fill="none" stroke="url(#route)" strokeWidth={2.2} strokeLinecap="round" className="fibre-flow" style={{ animationDelay: `${i * -1.7}s`, animationDuration: `${6 + i * 1.3}s` }} />
          </g>
        ))}
        {nodes.map(([cx, cy], i) => (
          <g key={i}>
            <circle cx={cx} cy={cy} r={16} fill="url(#node-glow)" className="node-pulse" style={{ animationDelay: `${i * 0.45}s` }} />
            <circle cx={cx} cy={cy} r={3.5} fill="#0b2a3b" stroke="#5fe39a" strokeWidth={1.6} />
          </g>
        ))}
      </svg>
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_40%,rgb(4_14_22/0.55)_100%)]" />
    </div>
  );
}
