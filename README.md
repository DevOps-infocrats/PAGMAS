# Pratap – Fibre Network Analytics

Dashboard and Management Review for the BSNL Bharat-Net O&M contract (Rajasthan, Haryana, Assam).
The weekly **Master Data … Daily track** workbook is imported by a Python backend, every figure is
recalculated from the GP-wise rows, and a Next.js dashboard shows it – including a downloadable
Management Review PowerPoint.

## Project structure

```
E:\PRATAP\BSNL
├── backend\                 Python FastAPI API – import, calculations, security, PPT/PDF   → backend\README.md
│   ├── app\                 application code (ingestion, analytics, api, security, reports)
│   ├── scripts\             generate_env.py (creates .env) · hash_password.py (admin password hash)
│   ├── tests\               security + accuracy tests against the real workbook
│   ├── var\app.db           SQLite database (users, audit log, imported datasets)   – git-ignored
│   ├── .env                 secrets and settings (SECRET_KEY, JWT, admin login)      – git-ignored
│   └── start.ps1            one-command start on port 8010
├── frontend\                Next.js 16 dashboard (React 19, Tailwind, ECharts)         → frontend\README.md
│   ├── src\app\             routes: /login, /dashboard (+ circle / block / gp insights, reports, operations, settings)
│   ├── src\features\        one folder per screen (overview, circle-insights, …, review)
│   ├── src\components\      shared UI: charts, tables, KPI cards, filters, layout, brand
│   └── src\lib\api\         typed API contracts + HTTP client (talks to the backend via /api)
├── data\                    company data – git-ignored, never public
│   ├── raw\                 source workbooks (e.g. Master Data V8.2 Daily track 09-10-26.xlsb)
│   ├── uploads\             workbooks uploaded from Data Operations
│   └── review_plan.json     management plan: monthly AMC plans + weekly closure targets (Target & Achievement page)
├── assets\brand\            Pratap logo source
└── docs\                    project report PDF + sample Management Review deck
```

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
