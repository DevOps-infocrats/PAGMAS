# Pratap – Fibre Network Analytics (frontend)

Next.js 16 (App Router) · React 19 · TypeScript · Tailwind CSS v4 · Radix UI primitives (shadcn/ui style) · Apache ECharts 6 · TanStack Table v9 · React Hook Form + Zod · Lucide icons.

Connected to the Python backend (`../backend`). The browser calls `/api/v1/*` on this server; `next.config.ts` rewrites it to `BACKEND_URL` (default `http://127.0.0.1:8010`), so the backend's httpOnly session cookie is first-party.

## Run it

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000  (start the backend first: ../backend/start.ps1)
```

Sign in with an account created on the backend (`python -m app.cli create-user …`). Admins see Data Operations and Settings (upload, reconciliation, users).

Modes (`.env.local`, see `.env.example`):

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_MODE` | `live` | `live` = backend data; `mock` = generated demo data, no backend (UI work only) |
| `BACKEND_URL` | `http://127.0.0.1:8010` | where the FastAPI server listens (server-side only) |

Quality checks: `npm run lint` · `npx tsc --noEmit` · `npm run build`

## Project structure

```
public/brand/                 Pratap logo (full, wordmark, mark – transparent PNGs)
src/
  app/
    layout.tsx                Root layout: font, theme script, preloader, providers
    login/                    Login page + form (RHF + Zod)
    dashboard/                Protected area (layout = sidebar/header shell)
      page.tsx                Circle Overview
      circle-insights/  block-insights/  gp-insights/
      reports/  operations/  settings/
  proxy.ts                    Login redirect (Next 16 "proxy" = old middleware)
  features/<page>/            Page views (one folder per screen)
  components/
    brand/                    Logo, Preloader (splash), inline-script helper
    layout/                   AppShell, Header, PageHeader/SectionHeader, AdminGuard, route progress bar
    navigation/               Sidebar, nav config, Ctrl+K command palette
    kpi/                      KpiCard, KpiTabs (GA4-style metric tabs), MoreMetrics, Sparkline
    charts/                   EChart wrapper, ChartCard, option builders, theme hook
    tables/                   DataTable (TanStack v9: search, sort, paginate, CSV export)
    filters/                  SearchableSelect, FilterBar, Circle/District/Block/Period filters
    reports/                  ReportPreview
    feedback/                 StatusBadge, AvailabilityValue, Empty/Error/Loading states
    ui/                       Button, Input, Select, Dropdown, Popover, Dialog, Tabs, …
  hooks/                      useApiQuery, useFilters (URL state), useSession, useDefaultSelection
  lib/
    api/                      contracts.ts (types), mock-client.ts, http-client.ts, index.ts (switch)
    mock-data/                Seeded generator for circles → districts → blocks → GPs, weeks, runs
    metrics/                  Metric catalogue (labels, units, polarity, tooltips) + calculations
    reports/                  Report service + demo PDF writer
    auth/  validations/  utils/
  types/                      Shared domain types
```

## Data flow

* `src/lib/api/contracts.ts` – response types; the backend (`backend/app/analytics/views.py`) returns exactly these shapes.
* `src/lib/api/http-client.ts` – live client (same-origin fetch, CSRF header on POST/PATCH, redirect to login on 401).
* `src/lib/api/mock-client.ts` + `src/lib/mock-data/` – demo mode only.
* `src/lib/auth/session.ts` + `components/providers/session-provider.tsx` – sign-in/out and the current user.
* `src/proxy.ts` – redirects signed-out users to /login (UX only; the backend enforces authentication and roles on every request).
* Metric labels/tooltips: `src/lib/metrics/definitions.ts` (rules are implemented in the backend; see backend/README.md).
