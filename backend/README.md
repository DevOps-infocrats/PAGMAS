# Pratap Network Analytics – Python backend

FastAPI + SQLAlchemy + pandas. It imports the **Master Data … Daily track** workbook (`.xlsb/.xlsx/.xlsm`), stores it in a database, recalculates every dashboard figure from the GP-wise rows and serves it through a secured REST API. It also renders the Management Review PowerPoint and the weekly PDF.

## How a request flows

```
upload .xlsb ─► api/admin.py ─► ingestion/service.py ─► ingestion/parser.py + workbook.py ─► database (models.py)
                                                                                                │
browser ─► Next.js /api proxy ─► main.py (middleware) ─► security/deps.py (session, role, CSRF)  │
                                   │                                                           ▼
                                   └─► api/analytics.py ─► analytics/views.py · review*.py ◄─ analytics/store.py (in-memory copy of the active dataset)
                                                         └► reports/review_pptx.py · reports/pdf.py ─► PPT / PDF download
```

* The active dataset is loaded once into pandas (`analytics/store.py`) and reused for every request; it is rebuilt automatically after a new import.
* `analytics/metrics.py` holds the metric rules; every page and the PPT use the same functions, so numbers never disagree.
* Each response is JSON in camelCase and matches `frontend/src/lib/api/contracts.ts`.

## Files and what they do

```
backend/
  app/
    main.py  config.py  db.py  models.py  cli.py
    ingestion/   workbook.py  parser.py  service.py
    analytics/   store.py  metrics.py  views.py  reconcile.py
                 review.py  review_periods.py  review_summary.py  review_targets.py  review_critical.py
    api/         auth.py  analytics.py  admin.py
    security/    core.py  deps.py  middleware.py
    reports/     review_pptx.py  pdf.py
  scripts/       generate_env.py  hash_password.py
  tests/         conftest.py  test_security.py  test_accuracy.py  test_review.py
  start.ps1 / start.sh       local start (Windows / macOS-Linux) on port 8010
  start-production.sh       production start (1 worker, proxy headers)
  requirements.txt          runtime dependencies    · requirements-dev.txt  + test tools
  .env.example              settings template
```

### Core

| File | Work |
|---|---|
| `app/main.py` | Creates the FastAPI app; adds security headers, body-size limit, rate limit, trusted hosts, CORS and the cross-site Origin check; maps errors to safe JSON (no stack traces); on start-up creates tables, creates/syncs the `.env` admin and auto-imports the newest workbook in `data/raw/` when the database is empty; mounts the routers under `/api/v1`. |
| `app/config.py` | All settings from `backend/.env` (Pydantic Settings): secret key and rotation key, JWT algorithm / issuer / audience, session length, login limits, CORS / hosts, upload size, business thresholds (98% healthy, 90% penalty), admin login. Rejects weak or placeholder keys at start-up. |
| `app/db.py` | SQLAlchemy engine and session (SQLite in `var/app.db` by default, PostgreSQL via `DATABASE_URL`); `init_db()` creates the tables. |
| `app/models.py` | Database tables: `users`, `audit_logs`, `datasets` (one per import), `validation_issues`, `dataset_weeks` (the file's W-nn weeks), `gps` (one row per GP), `gp_availability` (daily / weekly / monthly values), `reported_numbers` (O&M KEY NUMBERS), `master_blocks`. |
| `app/cli.py` | Command line: `create-user`, `import-file <path>`, `reconcile`. |

### Ingestion – reading the workbook

| File | Work |
|---|---|
| `ingestion/workbook.py` | Opens the workbook with python-calamine after checking the extension and the ZIP signature; helpers for header search, text normalising and dates. |
| `ingestion/parser.py` | Reads *GP Wise Data* (GP master columns, HOTO / AMC dates, daily, weekly W-nn and monthly availability columns, week date ranges), *Master Block* and the O&M *KEY NUMBERS*; validates every row and records issues (invalid OLT, RKM mismatch, AMC without HOTO, availability outside 0–100%, duplicates…). Phone numbers are deliberately not read. |
| `ingestion/service.py` | Runs an import: stores the file's hash, writes all rows in chunks, activates the new dataset only on success (previous one stays live on failure), keeps the last 3 datasets and refreshes the analytics cache. |

### Analytics – the calculations

| File | Work |
|---|---|
| `analytics/store.py` | Loads the active dataset into pandas (GPs, daily / weekly / monthly availability, weeks, reported numbers, master blocks); month-to-date availability (`mtd`) and per-week GP status (HOTO done, AMC, MTD, weekly value). |
| `analytics/metrics.py` | **Metric rules** (single source of truth): availability bands, block averages and `summarize()` – totals, HOTO, AMC, availability, GPs >98% / at 0%, NA, penalty-prone blocks, fibre RKM. |
| `analytics/views.py` | Builds the JSON for every dashboard page: meta (weeks, circles, blocks), Circle Overview, Circle Insights (period tables, band tables, daily bands), Block Insights (GP uptime), GP detail, GP list, search and the weekly report. |
| `analytics/reconcile.py` | Accuracy check: compares the calculated figures with the O&M KEY NUMBERS and explains every difference (e.g. the O&M month-to-date column covers fewer days). |
| `analytics/review.py` | Management Review entry point: builds one payload for the web page **and** the PPT (period columns, per-circle sections, band tables, insights) and calls the page modules below. |
| `analytics/review_periods.py` | Reporting-period rules reused by every review page: latest *completed* week, previous week, month cutoff (last data date), equal month windows (1–D of this month vs 1–D of the previous month). |
| `analytics/review_summary.py` | Page 1 *Executive Summary*: GPs >98%, blocks >98% and GPs at 0% (current vs previous week), AMC conversions vs incremental GPs by circle, AMC & monthly target table, data-backed insights and validation checks (overall = sum of circles, conversions = change in AMC count). |
| `analytics/review_targets.py` | Page 2 *Target & Achievement*: monthly AMC conversion plan (open month + next months) and weekly closure targets with achieved values; reads the management plan from `data/review_plan.json` (validated, re-read when the file changes) and the FRT count / operational target from the O&M sheet. |
| `analytics/review_critical.py` | Page 3 *Critical KPI – Blocks & GPs*: monthly & weekly performance table per circle (last two completed months, month to date, last three weeks – moves forward automatically). |

### API – the endpoints

| File | Work |
|---|---|
| `api/auth.py` | Login (rate limit, lockout, generic errors), logout (revokes all tokens), current user, change password. |
| `api/analytics.py` | Read-only data for signed-in users: meta, overview, circle / block / GP insights, GP list, search, notifications, weekly report (+ PDF), Management Review JSON and **PPT download** (chosen pages and circles, validation gate, audit entry). |
| `api/admin.py` | Admin only: upload a workbook, import runs and their issues, retry, reconciliation, user management, audit log. |

### Security

| File | Work |
|---|---|
| `security/core.py` | Argon2id password hashing and policy, JWT create / verify (pinned algorithm, issuer, audience, expiry, key rotation), CSRF tokens, sliding-window rate limiter. |
| `security/deps.py` | FastAPI dependencies used by every protected route: read and verify the session cookie, check the token version (revocation), check CSRF on state-changing requests, require the admin role; audit-log helper; trusted client IP. |
| `security/middleware.py` | Security headers (CSP, frame, nosniff, HSTS in production, no-store), request body size limit, global per-IP rate limit, request IDs. |

### Reports

| File | Work |
|---|---|
| `reports/review_pptx.py` | Management Review PowerPoint (python-pptx, 20×11.25"): cover with the Pratap logo, index, the five pages (pages 3–5 one slide per circle), thank-you slide. Native editable tables and charts; every number comes from the review payload. |
| `reports/pdf.py` | Weekly network performance report PDF (ReportLab). |

### Scripts and tests

| File | Work |
|---|---|
| `scripts/generate_env.py` | Creates `.env` with a random 64-character `SECRET_KEY` (never overwrites an existing file). |
| `scripts/hash_password.py` | Asks for the admin password (hidden), checks the policy and prints `ADMIN_PASSWORD_HASH=…` for `.env`. |
| `tests/test_security.py` | Login, rate limit, cookies, CSRF, token tampering / revocation, roles, uploads, input validation. |
| `tests/test_accuracy.py` | Figures against the workbook's O&M / Master Block sheets (runs when the real workbook is in `data/raw/`). |
| `tests/test_review.py` | Management Review: periods, KPI cards, targets, roadmap, weekly targets, critical table, PPT pages; `.env` admin sync and JWT key rotation. |

## Setup (Windows, PowerShell)

```powershell
cd E:\PRATAP\BSNL\backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt   # production servers: requirements.txt only
.\.venv\Scripts\python scripts\generate_env.py          # creates .env with a random SECRET_KEY
.\.venv\Scripts\python -m app.cli create-user --email you@company.com --name "Your Name" --role admin   # prompts for password
.\.venv\Scripts\python -m app.cli import-file "..\data\raw\Master Data V8.2 Daily track 09-10-26.xlsb"
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

Or simply run `.\start.ps1` (macOS / Linux: `./start.sh`). On first start, if no data is imported yet, the newest workbook in `data/raw/` is imported automatically. The server runs without auto-reload – restart it after changing code or `.env`.

Tests: `.\.venv\Scripts\python -m pytest -q` (accuracy tests run when the real workbook is in `data/raw/`).

New weekly file: sign in as admin → **Data Operations → Upload master data** (or `python -m app.cli import-file <path>`). The new dataset becomes active only after it has been imported successfully; the previous one stays live until then.

## Database (PostgreSQL)

The dashboard runs on **PostgreSQL** (`DATABASE_URL` in `.env`); without that line it falls back to SQLite
(`var/app.db`). Every sheet the dashboard uses is stored in the database at import – the dashboard never
opens the workbook at request time. Calculations stay in the backend (`analytics/`), on the data loaded
from the database.

| Table | Content |
|---|---|
| `datasets` | one row per imported workbook (status, data as of, active flag) |
| `gps` | GP Wise Data – one row per GP |
| `gp_availability` | daily (`D`), weekly (`W`), monthly (`M`) and monthly AMC (`MA`) availability; NULL = NA |
| `gp_availability_packs` | the same values as one compressed GP × period matrix per dataset + kind – written by imports and loaded by the dashboard (`gp_availability` is only read for older datasets, which get packed on first load); NaN = NA |
| `dataset_weeks` | W-nn weeks and their dates |
| `master_blocks`, `reported_numbers` | Master Block sheet, O&M key numbers (reconciliation) |
| `circle_sheet_values` | One-Time-Up rows of the Rajasthan / Haryana / Assam sheets |
| `validation_issues` | problems found while importing |
| `users`, `audit_logs` | logins and history |

Setup (once): create the login and the database in pgAdmin (Query Tool on `postgres`), one statement at a time:

```sql
CREATE ROLE partap_db WITH LOGIN PASSWORD '…';
CREATE DATABASE partap_db OWNER partap_db;
```

then in `.env`: `DATABASE_URL=postgresql+psycopg://partap_db:<password>@localhost:5432/partap_db` – a password with
`@ : / # % ? &` must be URL-encoded (`@` → `%40`, `#` → `%23`, `&` → `%26` …).
`scripts/migrate_to_postgres.py` copies users + audit log from SQLite and imports the workbook (run once).

Backup / restore (PowerShell):

```powershell
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -U partap_db -h localhost -F c -f "E:\PRATAP\backup\partap_db_$(Get-Date -Format yyyyMMdd).dump" partap_db
& "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" -U partap_db -h localhost -d partap_db --clean "E:\PRATAP\backup\partap_db_YYYYMMDD.dump"
```

## Column / sheet names (`data/column_map.json`)

The importer finds sheets and columns by **name** (case and spaces do not matter). When the workbook template
renames a column or a sheet, add the new name to its list in `data/column_map.json` – no code change, no restart:

```json
"gpColumns": { "amc_date": ["AMC Date", "AMC Dt"] }
```

The Escalation Matrix workbook uses the `escalationColumns` section the same way (e.g.
`"am_phone": ["AM Contact No", "AM Mobile"]`). Its fields include `ba` (business area) and `am_email` (AM e-mail,
shown on the area-manager tables of AMC Conversion; in full to admins only). Optional matrix columns that are not
found are listed in the import's message.

Save and upload the workbook again. Rules: the built-in names always keep working (the file only adds names);
the first listed name wins when a workbook contains several of them (a warning is recorded); a name given to two
fields is rejected; a broken file is ignored with a warning, so it never stops an upload. A missing required
column fails the upload (the active data stays) with the accepted names and a *suggested* similar column in the
message – the importer never guesses. Extra sheets and columns are ignored.

## Upload report

Every import stores a report (table `import_reports`, `GET /api/v1/ingestion/runs/{id}/report`, admin only, shown
on Data Operations when a run is selected): data-as-of vs the previous upload, GPs added / removed, GPs newly
HOTO-done / under AMC, corrected AMC / HOTO dates (with examples), new weeks, new / missing columns and sheets,
optional fields not found, issue counts, and plain-language warnings (older data date, >5% GPs missing, columns
gone). It is built inside the import in a savepoint and never fails an import.

## Metric definitions (validated against the workbook)

All rules live in `app/analytics/metrics.py`. Reconciliation against the O&M sheet: **30 exact matches, 10 explained differences, 0 unexplained** (see Data Operations → Accuracy check, or `python -m app.cli reconcile`).

| Metric | Rule |
|---|---|
| Total existing GPs | rows of *GP Wise Data* (incl. converted/closed) |
| Revised existing GPs | minus "Converted to Nagar Palika", "Permanently Closed", "GP deduction…" |
| HOTO done GPs / blocks | HOTO Date ≤ column end / blocks with ≥1 such GP |
| AMC GPs | AMC Date ≤ column end (AMC + Incremental); Incremental = category "Incremental" |
| Fibre | Total scope = Σ TOTAL RKM (all rows); AMC fibre = Σ TOTAL RKM of AMC GPs |
| MTD availability | mean of daily values from max(1st of month, AMC date) to the cutoff – identical to the sheet's formulas |
| Weekly availability | source `W-nn` columns (weeks are the file's own, Fri–Thu, e.g. W-41 = 2–8 Oct) |
| GPs >98% / at 0% | AMC GPs with availability strictly above 98 / exactly 0 (exactly 98 falls in 95–98); **NA is never counted as 0** |
| Penalty-prone blocks | mean AMC availability of the block < **90%** (source: "Penalty Prone Blocks <90%") |
| Bands | 0, 0–30, 30–50, 50–75, 75–85, 85–90, 90–95, 95–98, >98 – identical counts to the O&M tables |

Known source differences (explained, not errors):
* The *Oct'26 (AMC)* column (used by O&M "GPs above 98% (MTD)", "GPs at 0%", "Penalty Prone Blocks") averages **1–6 Oct**, while daily data runs to **8 Oct**. Recomputed for 1–6 Oct the dashboard reproduces the O&M values exactly; the dashboard itself shows the up-to-date figure.
* *One-Time Up GPs* in O&M come from an external report; the Management Review reads them from the circle sheets and marks them as such.

Data-quality checks recorded per import: invalid OLT values (dates/numbers), missing OLT/AM names, BSNL+BBNL ≠ TOTAL RKM, AMC without HOTO, AMC before HOTO, non-numeric/negative values, availability outside 0–100%, duplicate GP codes.

## Management Review (web page + PPT)

`analytics/review.py` builds one payload that feeds both the **Management Review** page and the deck (`reports/review_pptx.py`), so screen and PPT never disagree.

| Page | Module | Content |
|---|---|---|
| 1 Executive Summary | `review_summary.py` | GPs >98%, blocks >98%, GPs at 0% (current vs previous week), AMC & monthly target table, insights |
| 2 Target & Achievement | `review_targets.py` | circle AMC conversions, monthly AMC conversion plan, weekly closure targets |
| 3 Critical KPI – Blocks & GPs | `review_critical.py` | monthly & weekly performance table per circle |
| 4 Block Network Availability & Uptime | `review.py` | block availability band table per circle |
| 5 GP Network Availability & Uptime | `review.py` | GP availability band table per circle |

* Default reporting week = the latest **completed** week in the file; columns move forward automatically with new weeks.
* Targets: O&M "Target for Operational GP"; monthly plans and weekly closure targets from `data/review_plan.json`; RFP benchmark 75% of existing GPs.
* The PPT endpoint takes `sections` and `circles`, refuses to build a deck when a validation check fails, and records every download in the audit log.

## Mail Configuration and User Management (AMC Conversion e-mails)

Admin pages **Administration → Mail Configuration** and **→ User Management**; code in `app/mail/`, API in
`app/api/mail.py` (+ users in `app/api/admin.py`), tests in `tests/test_mail.py`.

| Module | Job |
|---|---|
| `audience.py` | who gets an e-mail and which GPs it covers |
| `report.py` | AMC figures of a GP set (same rules as AMC Conversion → Plan vs Execution) |
| `template.py` | `{{placeholders}}`, 3 built-in templates, validation, safe rendering (text + HTML) |
| `schedule.py` | next send time (daily / weekly / monthly, `MAIL_TIMEZONE`) |
| `service.py` | scheduler thread, slot claim, delivery, run log |
| `smtp.py` | SMTP settings check, connection, test mail |

**Audiences.** `am` / `sme` / `coh` / `cbh` come from the active Escalation Matrix (name + e-mail columns; one person
= one name within one circle; "Vacant…/Vacent-1" posts get nothing). An Area Manager's e-mail covers only the GPs
assigned to them (block-wise table); SME / COH / CBH get their circle (area-manager-wise table). `users` = dashboard
users: admins every GP, viewers only their assigned circles / districts / blocks (`user_scopes`; none = no e-mail).
**Filters** (state, business area, block, chosen people) narrow every recipient's GPs; one address gets one e-mail
(roles merged). Re-upload the Escalation Matrix once after this change so the SME / COH / CBH e-mails are stored.

**Templates** (`mail_templates`): `detailed`, `summary`, `action` are built in (editable, resettable, not deletable);
admins can add their own. Unknown placeholders are refused on save; values are HTML-escaped; tables are built by code.

**Sending.** Nothing is sent when saving / enabling a schedule (next time is always in the future), at start-up or in
tests. The scheduler runs only with `AMC_REPORT_EMAILS_ENABLED=true` (checks every 60 s). Each slot is claimed via the
unique `mail_runs(config_id, scheduled_for)` row → no double sends; a slot missed by > 6 h is SKIPPED. "Send Test
Mail" sends one plain message (5 per admin per 10 min).

**Environment** (see `.env.example`): `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_SSL` / `MAIL_USE_TLS` (not both),
`MAIL_USERNAME` + `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`, `MAIL_TIMEZONE`, `AMC_REPORT_EMAILS_ENABLED` (default false).
`SMTP_APPROVAL_EMAILS_ENABLED` is read but reserved for approval e-mails. Bad mail settings never stop the API.

## Security

* **Passwords:** Argon2id hashes, strength policy (≥12 chars, 3 character classes), no default accounts.
* **Secrets in `.env` only:** `SECRET_KEY` (+ optional `SECRET_KEY_PREVIOUS` for rotation without signing everybody out), `JWT_ALGORITHM` / `JWT_ISSUER` / `JWT_AUDIENCE`, and the admin login `ADMIN_EMAIL` + `ADMIN_PASSWORD_HASH` (create the hash with `python scripts\hash_password.py`; a plain `ADMIN_PASSWORD` is accepted in development only). The admin is created on start-up when missing; `ADMIN_SYNC_PASSWORD=true` resets an existing admin's password to the `.env` value and revokes its sessions. Weak or placeholder keys stop the server from starting.
* **Sessions:** signed JWT (pinned HS256/384/512, audience/issuer/expiry/nbf/jti required) in an **httpOnly, SameSite=Lax** cookie (Secure in production). Logout, password change, role change or deactivation bump `token_version` → all old tokens are revoked.
* **CSRF:** double-submit token (`pratap_csrf` cookie + `X-CSRF-Token` header) on every state-changing request, plus an Origin/Referer allow-list check.
* **Brute force:** login rate limit per IP and per account (5 / 15 min), account lockout after 10 failures, generic error messages (no user enumeration), constant-time checks.
* **Authorization:** every data endpoint requires a session; ingestion, reconciliation, users and audit require the **admin** role (enforced server-side).
* **Input validation:** strict patterns for all ids and query parameters; Pydantic bodies; validation errors never echo submitted values.
* **Uploads:** admin only, extension allow-list + ZIP signature check, size limit (streamed), random server-side file name, background processing, one import at a time.
* **HTTP hardening:** CSP `default-src 'none'`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Cache-Control: no-store`, HSTS in production, trusted hosts, CORS allow-list, global per-IP rate limit, request IDs, no stack traces in responses, `/docs` disabled in production.
* **Privacy:** phone numbers of splicers/FE/AM/SPOC in the workbook are **not imported**; only the AM name is kept.
* **Audit log:** logins (success/failure/lockout), logouts, uploads, retries, user changes, PPT downloads (`GET /api/v1/audit`).
* Source and uploaded workbooks live in `data/` which is outside both apps and git-ignored.

For production: set `APP_ENV=production`, serve both apps behind HTTPS (e.g. Nginx/IIS reverse proxy), use PostgreSQL via `DATABASE_URL`, run uvicorn with a single worker (or move rate limiting to Redis for several workers), and back up the database.

## API (all under `/api/v1`, JSON, camelCase)

| Method & path | Access |
|---|---|
| `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `POST /auth/change-password` | public / signed-in |
| `GET /meta` · `/overview` · `/circles/{id}/insights` · `/blocks/{id}/insights` · `/gps` · `/gps/{code}` · `/search` · `/notifications` | signed-in |
| `GET /reports/weekly` · `GET /reports/weekly.pdf` | signed-in |
| `GET /reviews/management` · `GET /reviews/management.pptx?sections=…&circles=…` (Management Review page / PPT deck, same payload) | signed-in |
| `GET /ingestion/runs` · `GET /ingestion/runs/{id}/issues` · `POST /ingestion/upload` · `POST /ingestion/runs/{id}/retry` · `GET /ingestion/reconciliation` | admin |
| `GET/POST /users` · `PATCH /users/{id}` · `GET /audit` | admin |

Query parameters: `week=W-41&compare=W-40`, optional `circle`, `district`, `block`. Interactive docs at http://127.0.0.1:8010/docs (development only).
