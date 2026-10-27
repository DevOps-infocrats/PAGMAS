# Pratap – Fibre Network Analytics

Dashboard and Management Review for the BSNL Bharat-Net O&M contract (Rajasthan, Haryana, Assam).
The weekly **Master Data … Daily track** workbook is imported by a Python backend, every figure is
recalculated from the GP-wise rows, and a Next.js dashboard shows it – including a downloadable
Management Review PowerPoint.

## Project structure

```
BSNL/
├── backend/                 Python FastAPI API – import, calculations, security, PPT/PDF   → backend/README.md
│   ├── app/
│   │   ├── main.py          app factory: middleware, error handling, start-up, /api/health + /api/ready
│   │   ├── config.py        all settings from .env (validated; production refuses unsafe values)
│   │   ├── db.py, models.py SQLAlchemy engine/session and tables
│   │   ├── api/             HTTP layer only: auth, analytics (read), admin (upload, users), escalation
│   │   ├── ingestion/       workbook → validated rows → database (one import at a time)
│   │   ├── analytics/       in-memory snapshot of the active dataset + every KPI rule
│   │   ├── reports/         Management Review PPTX, weekly PDF
│   │   └── security/        passwords, JWT, CSRF, rate limits, security headers
│   ├── scripts/             generate_env.py · hash_password.py · migrate_to_postgres.py
│   ├── tests/               security, accuracy (real workbook), review, ingestion, hardening tests
│   ├── requirements.txt     runtime deps  ·  requirements-dev.txt adds the test tools
│   ├── start.ps1 / start.sh local start on port 8010  ·  start-production.sh (1 worker, proxy headers)
│   └── .env                 secrets and settings – git-ignored (template: .env.example)
├── frontend/                Next.js 16 dashboard (React 19, Tailwind 4, ECharts)        → frontend/README.md
│   ├── src/app/             routes: /login, /dashboard/* (overview, insights, AMC, field team, review, operations, settings)
│   ├── src/features/        one folder per screen
│   ├── src/components/      shared UI: charts, tables, KPI cards, filters, layout, navigation, brand
│   ├── src/lib/api/         typed API contracts + HTTP client (talks to the backend via /api)
│   └── src/proxy.ts         route gate (redirects to /login without a session)
├── deploy/                  nginx.conf – HTTPS reverse proxy for a server install
├── data/                    company data – git-ignored, never public
│   ├── raw/                 source workbooks; the newest master file is imported on first start
│   ├── uploads/             workbooks uploaded from Data Operations (old ones are cleaned up automatically)
│   └── review_plan.json     management plan: monthly AMC plans + weekly closure targets
├── assets/brand/            Pratap logo source
└── docs/                    project report PDF + sample Management Review deck (build_report.py)
```

Layering rule: `api/` only parses requests and checks roles, `analytics/` and `ingestion/` hold the logic and never
import from `api/`, and the frontend only ever talks to `/api/v1` through `src/lib/api`.

## How it works

```
 Excel workbook (.xlsb)                      Backend (FastAPI, port 8010)                         Frontend (Next.js, port 3000)
 ─────────────────────                       ────────────────────────────                         ─────────────────────────────
 GP Wise Data, Master Block,   ──upload──►   1. ingestion: read + validate every row   ──►  DB
 O&M (KEY NUMBERS), circle sheets            2. analytics: in-memory store, metric rules
                                             3. api: JSON per page (login + role checked)  ◄──/api/v1──  pages, charts, tables
 data\review_plan.json         ──────────►   4. reports: Management Review PPT, weekly PDF ──download──► browser
```

1. **Import** – an admin uploads the weekly workbook (Data Operations → Upload master data). The backend checks
   the file, reads *GP Wise Data*, *Master Block*, *O&M* and the circle sheets, validates each row and stores it as a
   new dataset. The new dataset goes live only after a successful import; the previous one stays live until then.
2. **Calculate** – every number (HOTO, AMC, availability bands, penalty-prone blocks, targets …) is computed from the
   GP-wise rows with the workbook's own rules. Nothing is copied from summary sheets; the O&M KEY NUMBERS are used
   to *check* the results (Data Operations → Accuracy check).
3. **Show** – the browser only talks to the Next.js server; `/api/*` is proxied to the backend, so the session cookie
   stays first-party and httpOnly. Week and month columns come from the data, so a new week (W-42, W-43 …) appears
   automatically after the next upload.
4. **Report** – *Management Review* shows five pages and downloads the same figures as a PPT
   (cover with logo, index, the chosen pages, thank-you slide).

## Dashboard pages

| Page | What it shows |
|---|---|
| Circle Overview | Scope, HOTO, AMC, availability and network health for all circles |
| Circle Insights | One circle: block list, HOTO / AMC status, GP and block uptime month-wise and week-wise |
| Block Insights | One block: KPIs, GP uptime, OLTs, GP list |
| GP Insights | One GP: availability history, uptime days per band, HOTO / AMC events |
| Management Review | 1 Executive Summary · 2 Target & Achievement · 3 Critical KPI – Blocks & GPs · 4 Block Network Availability & Uptime · 5 GP Network Availability & Uptime – plus **Download PPT** |
| Data Operations *(admin)* | Upload workbook, import runs and data-quality issues, accuracy check vs the O&M sheet |
| Settings *(admin)* | Users and roles |

## Run (two terminals)

```powershell
# 1. API  (http://127.0.0.1:8010)
cd E:\PRATAP\BSNL\backend
.\start.ps1

# 2. Dashboard  (http://localhost:3000)
cd E:\PRATAP\BSNL\frontend
npm install
npm run dev
```

Open http://localhost:3000/login and sign in with the admin account. Stop either server with **Ctrl + C**.
The backend runs without auto-reload: restart it after changing backend code or `.env`.

macOS / Linux: `cd backend && ./start.sh`, then `cd frontend && npm install && npm run dev`.

## Production deployment

```
Browser ──HTTPS──► nginx (443, TLS, real client IP) ──► Next.js (3000) ──/api/*──► FastAPI (8010, 1 worker) ──► PostgreSQL
```

1. `backend/.env`: `APP_ENV=production`, `DATABASE_URL=postgresql+psycopg://…`, `CORS_ORIGINS=["https://<your-domain>"]`,
   `TRUSTED_HOSTS=["<your-domain>"]`, `ADMIN_EMAIL` + `ADMIN_PASSWORD_HASH` (`python scripts/hash_password.py`).
   The API refuses to start in production when one of these is unsafe (localhost-only origins, plain password …).
2. Start `backend/start-production.sh`, then `cd frontend && npm ci && npm run build && npm start`, with
   `deploy/nginx.conf` in front (replace `analytics.example.com` and the certificate paths).
3. Run the API with **one worker** (the import lock, rate limits and the data snapshot live in the process).
4. Probes: `GET /api/health` (process up) and `GET /api/ready` (database reachable) – 503 when not ready.

## Disk usage – why the folder is ~2 GB

Only about 3 MB of it is source code. The rest is generated or company data, all git-ignored and safe to rebuild:

| Folder | Size | What it is | Safe to delete? |
|---|---|---|---|
| `frontend/node_modules` | ~715 MB | npm packages (Next.js, React, ECharts, TypeScript …) | yes – `npm install` restores it |
| `frontend/.next` | ~400 MB | Next.js dev/build cache | yes – recreated on the next `npm run dev` / `build` |
| `backend/.venv` | ~530 MB | Python packages (pandas, numpy, FastAPI …) | yes – `pip install -r requirements-dev.txt` restores it |
| `data/uploads` | ~170 MB | every workbook uploaded so far (many duplicates) | old/failed uploads are now pruned automatically |
| `backend/var/app.db` | ~55 MB | old SQLite database from before the PostgreSQL move | yes, once PostgreSQL is confirmed as the live database |

## Weekly routine

1. **Data Operations → Upload master data** with the new workbook.
2. Check **Accuracy check (reconciliation)** on the same page – every figure should be *Match* or *Explained*.
3. Update `data\review_plan.json` when the monthly plans or weekly closure targets change.
4. **Management Review → Download PPT**.

## Configuration and security

* All secrets and settings live in `backend\.env` (see `backend\.env.example`): `SECRET_KEY`, JWT issuer / audience /
  algorithm, admin login (`ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`), CORS, trusted hosts. Never commit `.env` or `data\`.
* Passwords are stored as Argon2id hashes; sessions are signed JWTs in httpOnly cookies with CSRF protection, login
  rate limiting and account lockout. Details: `backend\README.md → Security`.
* Port 8000 belongs to another project on this machine – this project uses **8010** (API) and **3000** (dashboard).
