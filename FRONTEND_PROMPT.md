# Build a Professional Fiber Network Data Analytics Dashboard — Frontend Only (Phase 1)

Act as a senior frontend engineer, UI/UX designer, and data visualization specialist. Build a production-quality, enterprise-level fiber network operations and data analytics dashboard for a telecommunications infrastructure project, branded for **Pratap** ("Carving Lives").

The backend will be built later in **Python (FastAPI)**. Do NOT build any backend now — only the frontend, structured so the Python APIs can be plugged in cleanly in Phase 2.

## 1. Technology stack

Use:
- Next.js (latest stable) with App Router
- React and TypeScript (strict mode)
- Tailwind CSS
- shadcn/ui
- Apache ECharts (via `echarts-for-react` or a thin wrapper) for charts and time-series visualizations
- TanStack Table for interactive data tables
- Lucide React icons
- React Hook Form and Zod where useful for forms and validation
- `next/font` with **Inter** (or Plus Jakarta Sans) — no other font sources

Use a clean component-based architecture. Do not build the entire application inside one component.

## 2. Important development constraints

This is Phase 1: FRONTEND ONLY.

- Do not build the Python backend yet.
- Do not connect to Google Drive or PostgreSQL yet.
- Do not claim that actual Excel data has been loaded.
- Use realistic, centralized mock data for visual development.
- Clearly label the environment as DEMO DATA until real backend APIs are connected.
- Create a typed API service layer with mock implementations so it can later be replaced with Python FastAPI endpoints (one env variable switch, e.g. `NEXT_PUBLIC_API_MODE=mock|live`).
- Do not hardcode different, unrelated KPI values in individual components.
- Use shared TypeScript interfaces and centralized mock datasets.
- Make all navigation, filters, dropdowns, chart interactions, tables, date controls, report previews and buttons functional where appropriate.
- Never invent or display fake live-data synchronization status.
- Keep company Excel files and sensitive information outside the `public/` directory and exclude local data files (`/data`, `*.xlsx`, `*.csv`, `.env*`) from Git.

## 3. Design direction — Google Analytics 4 + Cloudflare dashboard style

The UI must feel **unique, calm, clean and professional** — in the spirit of the **Google Analytics 4** and **Cloudflare** dashboards. It must NOT look congested, crowded or like a generic admin template. Whitespace and hierarchy matter more than showing everything at once.

### 3.1 Brand

- Use the supplied logo: `assets/brand/pratap-logo.png` → copy to `public/brand/pratap-logo.png` and render with `next/image`.
- Logo appears in: sidebar header, collapsed sidebar (icon/compact version — crop or scale, do not redraw), login page, preloader, and report preview header.
- Brand palette taken from the logo: **green → blue gradient** (approx. `#3DBE4B` → `#1E88E5`; sample the exact values from the image). Use the gradient **sparingly** — logo, preloader, primary button hover, active-nav indicator, top progress bar. Never as large background fills.
- Do not invent a different logo or tagline.

### 3.2 Visual language

- Light theme first: page background a very soft neutral (e.g. `#F8F9FA`), cards pure white, 1px hairline borders (`#E5E7EB`), almost no shadows (at most a very subtle one on hover).
- **Light, clean sidebar** (Cloudflare style) with grouped sections, small muted section labels, thin active indicator bar in the brand gradient. Fully collapsible to an icon rail.
- One primary accent (brand blue). Status colours only for meaning: green = healthy, amber = warning, red = critical, grey = NA / no data.
- Typography scale: page title 24px semibold, section title 16px semibold, card label 13px medium muted, KPI value 28–32px semibold with tabular numerals.
- Generous spacing: 24px page padding, 16–24px gaps between cards, 8px radius on cards (not overly rounded).
- Dark-mode-ready via CSS variables (shadcn tokens). Provide a theme toggle in the profile menu.

### 3.3 KPI cards — GA4 "scorecard" style (must be unique, not generic boxes)

Each KPI card shows, in this order:
1. Metric label (small, muted) + info icon with tooltip giving the metric definition and reporting period.
2. Big value with unit (`%`, `RKM`, `GPs`, `Blocks`).
3. Comparison chip: ▲/▼ change vs previous week — green/red by whether the change is good or bad for that metric (e.g. *more* 0%-uptime GPs is red). Use **pp** for percentage metrics.
4. A small sparkline of the last 8 weeks (only if history exists; otherwise nothing — never a fake line).

Layout rules to avoid congestion:
- **Maximum 4 KPI cards per row** on desktop, 2 on tablet, 1–2 on mobile.
- On pages with many KPIs, show **4 hero KPIs** at the top and put the rest in a compact, collapsible **"More metrics"** section (smaller cards or a clean definition-list grid).
- **GA4-style metric tabs**: on each overview page, the hero KPI cards double as tabs — clicking one switches the main trend chart below to that metric.
- Each page should have one clear primary chart; secondary charts sit below in a 2-column grid with clear section headers (Cloudflare style: title, one-line description, optional action on the right).

### 3.4 Charts

- Minimal gridlines (horizontal only, light grey), no 3D, no heavy borders, no pie charts with more than 5 slices (use bars instead).
- Consistent colour order across all charts; brand blue for the primary series.
- Clean tooltips with reporting date, value and unit; legends only when there is more than one series.
- Loading skeletons shaped like the chart, and clear empty/NA states.

### 3.5 Preloader and loading states

- **App preloader (splash)**: shown on first load of the session. Centered Pratap logo with a soft fade/scale-in, a thin animated **"fibre light" line** (a glowing pulse travelling along a line in the green→blue gradient) beneath it, and the tagline "Carving Lives". Keep it elegant and short (≈ 1–1.5 s or until the app shell is ready, whichever is longer, max ~2.5 s). Do not show fake percentage numbers.
- Show the splash only once per browser session (`sessionStorage`), not on every route change.
- Respect `prefers-reduced-motion` (static logo + simple fade).
- **Route changes**: a thin gradient top progress bar (no full-screen loader).
- **Data loading inside pages**: skeletons for KPI cards, charts and tables.

### 3.6 Responsiveness and accessibility

- Responsive for desktop, tablet and mobile (sidebar becomes a slide-over drawer on mobile).
- WCAG AA contrast, visible focus rings, full keyboard navigation, meaningful `aria-label`s on icon buttons and charts.

## 4. Application layout

Build a collapsible left sidebar, a top header, a breadcrumb, a page title and a main content area.

Sidebar navigation (grouped):
- **Analytics**: 1. Circle Overview, 2. Circle Insights, 3. Block Insights, 4. GP Insights
- **Reporting**: 5. Management Reports
- **Admin** (admin only): 6. Data Operations, 7. Settings

The sidebar has the logo area, active-page highlighting, icons, profile information and logout.

Top header (keep it light and uncluttered):
- Global search (search circles, blocks, GPs — keyboard shortcut `Ctrl/⌘ + K` opens a command palette)
- Reporting date/week selector
- Notification icon with demo notifications
- Data environment badge showing **DEMO DATA**
- Refresh control (refreshes mock data only)
- User profile menu (profile, theme toggle, logout)

Preserve selected state, district, block and GP filters while navigating between pages (use URL search params as the source of truth so links are shareable, plus a small context/store).

## 5. Login page

Split layout: left side brand panel (logo, tagline, subtle fibre-line illustration using the brand gradient), right side the form.

- Pratap logo
- Email and password inputs
- Show/hide password
- Remember-me option
- Forgot-password link (demo message)
- Login button with validation and loading state
- Friendly error messages

For Phase 1, implement only a clearly marked demo authentication flow with mock users (e.g. one admin and one viewer, shown on the login page as "Demo accounts"). Never hardcode real production credentials or claim the login is secure production authentication.

Protect dashboard routes using a clean frontend demo-auth mechanism (middleware + cookie). Clearly document that real authentication and authorization must be implemented in the Python backend later.

## 6. Circle Overview page

Organization-wide overview for all circles/states.

**Hero KPIs (4, act as metric tabs for the main chart):**
- Total GPs
- AMC GP Percentage
- GPs Above 98% (MTD)
- Penalty-Prone Blocks Below 85%

**More metrics (collapsible compact section):**
- Total States
- Total Blocks
- Revised Existing GPs
- Total HOTO Done Blocks
- Total HOTO Done GPs
- Total AMC GPs
- GPs at 0% (MTD)
- One-Time UP GPs (Sept-26)

Charts and tables:
- State-wise Comparison
- State-wise Network Health
- Converted to NP / Permanently Closed
- State-wise HOTO Done — Blocks
- State-wise HOTO Done — GPs
- State-wise Fibre Route (RKM)
- State-wise Incremental GPs
- GPs Above 98% — Same Days Comparison
- State-wise NA GPs
- Area Manager Performance — State-wise

Group these into clear sections (e.g. *Network Health*, *HOTO Progress*, *Fibre & Growth*, *People*) so the page reads top-to-bottom like a story, not a wall of charts.

Requirements:
- KPI cards follow section 3.3.
- Searchable, sortable state comparison table.
- State/circle selector dropdown.
- Clicking a state or circle opens Circle Insights with that selection preserved.
- Chart tooltips, legends, date/week filters and loading/empty states.
- Realistic but internally consistent demo data.

## 7. Circle Insights page

Searchable state/circle dropdown.

Hero KPIs: Total GPs, HOTO Done (GPs), AMC GPs, AMC Availability.
More metrics: Total Districts, Total Blocks, Total Fibre Route.

Charts and tables:
1. Block-wise GP Count — selector for Top 10 / Top 20 / Top 50 / All.
2. HOTO / AMC Status — clean tabular view (completed, pending, applicable) plus a chart if useful.
3. GP Uptime Performance (AMC GPs) — time-series line chart.
4. Block Uptime Performance — time-series line chart.

Provide a reporting-period selector and meaningful axes/legends for time series.

Searchable block table: Block name, District, Total GPs, HOTO completed, HOTO pending, AMC GPs, Availability, Total RKM. Clicking a block opens Block Insights with the hierarchy preserved.

## 8. Block Insights page

Circle, district and block selectors (cascading).

Hero KPIs: Total GPs, Total RKM, HOTO Done, AMC GPs.
More metrics: BSNL Existing RKM, BBNL Existing RKM, HOTO Pending, Non-AMC GPs.

Charts and tables:
- GP-wise HOTO Status
- GP-wise RKM
- BSNL vs BBNL Fibre
- GP Uptime Performance (AMC GPs)
- GP-wise Availability
- OLT Distribution
- AMC / Incremental
- Incremental GPs

Searchable GP table: GP name/code, District and block, HOTO status, AMC status, BSNL RKM, BBNL RKM, Total RKM, Availability, OLT location. Clicking a GP opens GP Insights.

## 9. GP Insights page

Detailed page for one Gram Panchayat.

Header: GP name and stable identifier; circle/state › district › block breadcrumb; reporting period; current reporting status badge.

Summary cards: HOTO status, AMC status, Total RKM, BSNL RKM, BBNL RKM, Availability, OLT location.

Sections:
- Availability trend over time
- HOTO history where available
- AMC information and coverage dates where available
- Fibre network details
- OLT details
- Incremental/existing GP classification
- Historical changes and data-quality warnings

If historical data is not available, show "History unavailable" rather than fabricating a trend.

## 10. Management Reports page

Dedicated management reporting workspace.

Filters: Circle/state, reporting week, compare-with week, optional district and block, reporting date range. Default comparison: Week 41 vs Week 40, user-selectable.

Report sections:
- Executive summary
- KPI comparison table
- State/circle performance ranking
- HOTO progress
- AMC coverage and availability
- Fibre route and incremental GP changes
- Penalty-prone blocks
- Low-availability GPs
- Data-quality exceptions

KPI comparison table columns: Metric, Previous week value, Current week value, Absolute change, % or pp change as appropriate, Trend indicator.

Report preview styled like a clean A4 document with the Pratap logo in the header and a visible **DEMO — NOT A VERIFIED REPORT** watermark. Download PDF button: in Phase 1 it downloads a clearly labelled DEMO PDF (or uses the browser print-to-PDF of the preview). Structure the report service so it can later call the Python backend to generate the real PDF. Never present a frontend mock report as a verified production report.

## 11. Data Operations page

Admin-only page for the future automated ingestion system. Demo placeholders for: Last successful import, Latest file name, Processing status, Records accepted, Records rejected, Validation errors, Processing duration, Ingestion history.

Include file-processing status filters and a retry button that is explicitly demo-only. Do not simulate real Google Drive integration.

## 12. Data architecture and reusable components

Project structure (adjust sensibly for the App Router):

```
public/
  brand/pratap-logo.png
src/
  app/
    login/
    (dashboard)/
      layout.tsx
      page.tsx                 # Circle Overview
      circle-insights/
      block-insights/
      gp-insights/
      reports/
      operations/
      settings/
  components/
    brand/        # Logo, Preloader
    layout/
    navigation/
    kpi/
    charts/
    tables/
    filters/
    reports/
    feedback/     # EmptyState, ErrorState, LoadingSkeleton
  lib/
    api/          # service interfaces + mock implementation + (future) http client
    mock-data/
    metrics/      # calculation logic (never inside UI components)
    utils/
    validations/
  types/
  hooks/
```

Reusable components: Logo, Preloader, KpiCard, KpiTabs, MetricsGrid, ChartCard, SectionHeader, FilterBar, SearchableSelect, DataTable, StatusBadge, PageHeader, EmptyState, LoadingSkeleton, ErrorState, ReportPreview, CommandPalette.

TypeScript types for Circle, District, Block, GP, HOTO status, AMC status, fibre route, availability history, KPI data and weekly report comparisons. Shape the types like the JSON the future FastAPI endpoints will return (snake_case → camelCase mapping in one place).

Centralized mock-data module with a consistent hierarchy, generated from a fixed seed so values are stable across reloads: selecting a circle filters its blocks, selecting a block filters its GPs, and clicking through pages always shows matching records.

## 13. Analytics display rules

- Clearly distinguish zero from NA/missing data.
- Label availability and uptime in percentage units.
- Label fibre route values in RKM or the source-defined unit.
- Never sum repeated daily snapshots as if they were unique GPs.
- Use explicit reporting dates for all time-series charts.
- Use percentage-point change for percentage metrics when comparing two percentages.
- Include metric tooltips and reporting-period labels.
- Avoid hardcoding calculation logic in UI components.
- Indian number formatting (e.g. 1,23,456) for counts.
- Make the UI ready for server-driven pagination and filtering.

## 14. Quality requirements

- No TypeScript errors, no broken imports, no console errors.
- No nonfunctional navigation controls.
- Avoid unnecessary dependencies.
- No huge monolithic components.
- Do not overwrite unrelated existing files or project configuration.
- Sensible error, loading, empty and responsive states.
- The application builds successfully.

## 15. Deliverables

First inspect the existing project directory and package configuration. Reuse the existing project where possible (the folder currently contains only `assets/brand/pratap-logo.png` and this prompt).

Then:
1. Implement the frontend inside a `frontend/` folder (leave room for a sibling `backend/` folder for the Python API in Phase 2).
2. List the files created or changed.
3. Provide exact installation and development commands.
4. Run lint, type-check and production build.
5. Fix errors before declaring completion.
6. Write a `frontend/README.md` documenting where mock data lives and how to replace it with Python FastAPI APIs in Phase 2 (list the expected endpoints and response shapes).
7. Clearly state that authentication, Google Drive automation, database integration and real PDF generation are not yet implemented.

Build the actual working frontend, not just a design description or a static screenshot.
