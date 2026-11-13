# Data uploads – format, storage and validation

Two data files feed the dashboard. Both are uploaded on **Data Operations → Upload data file**: choose the
**file type**, pick the file, read the **check report**, then **Confirm import**. Nothing changes on the
dashboard before the confirm.

## 1. Master Data workbook

One workbook ("Master Data … Daily track") with two data sheets, checked in one upload. Columns are found by their
**header name, never by position** – any order works; letter case, spaces and punctuation do not matter
(`AMC/Incremental` = `AMC / Incremental`). The rules live in one place, `backend/app/ingestion/template.py`
(the upload check, the importer's names and the downloadable templates all come from it).

| | GP Wise Data | Master Block |
|---|---|---|
| File type | `.xlsb` or `.xlsx` (`.xlsm` refused) | same workbook |
| Header row | found in the first 15 rows (row 3 in the template – the row above holds the week ranges / weekdays) | found in the first 15 rows (row 4 in the template) |
| **Required** (missing = file rejected) | Circle, BA, DISTRICT, BLOCK, Block Code, GP, GP Code, GP Type, TOTAL RKM, HOTO Date, Letter submission date AMC Incremental, AMC / Incremental, AMC Date, AM Name, 5% Contractual Incremental+ Additional AMC, Planned Date, Ach Date | State, BA, District, Block Name, Block Code, HOTO Done Date, Total GP Count, Existing GPs, New GPs |
| **Optional** (read if present, NA if absent – never a reason to reject) | New Block Code post BoQ, New Block Name post BoQ, Block Changed, Block HoTo Status, LOCATION CODE, Converted to NP & Closed, Phase, OLT Location, BBNL Live KM, BSNL Live KM, LMS /AMC Date, Lot wise, <50 % Availability Last 4 M, Current Status, Letter Status, Letter submission Date, Approval Status, FRT Code, splicer / FE / AM / SHQ contacts, Block Priority | FRT CODE, HOTO Done GPs, AMC GP GPs, Non AMC Count, BSNL / BBNL Existing RKM, Total RKM, Lot Wise, AMC, Incremental, Achieved, Shortfall / Penalty, Target Week, Target Date, Penalty Date, Block Status |
| **Time-varying** (by pattern – never a reason to reject) | day = a real date per column (right after the W-nn columns) · week = `W-46` with its range (`7-13 Nov`) in the row above · month = the 1st of the month as a date · `Nov'26 (AMC)` · status columns (`April`, `WK-46`, not used) | `Nov Avail` / `Nov Avg Avail [TD]` (first the ALL GPs group, then the AMC GPs group) · `W46 Avail` · day dates · targets (`Nov 5% Inc. Target`, `GAP Nov` – not used) |
| Any other column | ignored, listed as **not used** in the report | same |
| Business key | GP Code (one row per GP) | Block Code (one row per block) |
| Max size | `UPLOAD_MAX_MB` (60 MB) | |

Why these are required: the dashboard, the tickets and the e-mails are built from them (location, AMC status and
dates, the AMC conversion plan, the Area Manager, the block GP counts). A renamed required column is never guessed:
the report suggests the similar column of the file; an admin can add the new name on Data Operations → Column
names (`data/column_map.json`).

### Templates (Data Operations → Upload → expected format)

Generated on download from the same rules, so always current:
`/api/v1/ingestion/template/gp.xlsx` (GP Wise Data), `…/block.xlsx` (Master Block) and `…/master.xlsx` (both sheets
in one workbook, ready to fill and upload). Each sheet has two clearly separated parts:

* **Section A (green) – REQUIRED columns**, exact names, with 2 example rows (GP codes 999901 / 999902).
* **Section B (orange) – availability columns: EXAMPLES, not fixed** – a few day / week / month columns with the
  two-row header (week range / weekday above). *"Add as many days / weeks / months as you have. Uploading only the
  current week / month is fine. Files are NEVER rejected because of these columns."*

A **Read Me** sheet lists every column with its bucket and what the dashboard uses it for.

### Partial uploads and history

A file may start later than the previous one (only W-45 onwards, only November). Nothing is required from earlier
periods:

* **Within the file**: the data date ("data as of") is the latest day with a value. A day / month missing before
  the latest one, a week label that is not a 7-day range, a period written twice (both column letters named),
  date columns away from the daily block → **warnings**. A week the file skipped is built from the daily values.
* **Across uploads**: every import merges its periods into the history – daily into `gp_daily_history`, weekly /
  monthly (GP Wise and Master Block) into `period_history`. A period in both keeps the values of the file with the
  **later data date**; an older file only fills periods the history does not have. The dashboard shows the
  earlier weeks / months a new file no longer has from this history (the report lists them as "kept from earlier
  uploads"). Kept for `PERIOD_HISTORY_MONTHS` (6) months before the newest data date.
* Fill the history from older files without importing them: `python -m app.cli backfill-periods [files…]` (no
  files = the stored files of the kept imports) and `python -m app.cli backfill-daily <file>`.

## 2. Escalation Matrix

| | |
|---|---|
| File type | `.xlsx` or `.xlsb` |
| Sheet | any sheet whose header row has the required columns (`All` in the template) |
| Required columns | Circle, GP Code, FRT Code, FE Name |
| Optional columns | BA, District, Block Name, Block Code, GP, Splicer Name / number, FE Number, FE Email ID, AM Name / Number / Email ID, SME Name / Number / Email ID, COH / No. / Email ID, CBH / No. / Email ID |
| Business key | GP Code (matched to the master data's GP Code) |

Templates: `frontend/public/templates/Escalation Matrix Template.xlsx` / `… Sample.xlsx`.

A GP without **AM Name** does not appear in Area Manager / FE lists (AM-wise targets, Generate Ticket) – the
check report lists those rows. The active matrix can also be corrected on **Field Team & Escalation → Escalation
Sheet** (admins); a later matrix upload replaces those edits – export the sheet and use it as the next upload.

## Validation – strict order, first failure stops

1. **File** – extension (`.xlsx` / `.xlsb`), not empty, a genuine workbook package (a renamed file is refused),
   zip-bomb guard (`ZIP_MAX_UNCOMPRESSED_MB`, `ZIP_MAX_RATIO`).
2. **File type** – the content must be the file chosen in the dropdown.
3. **Duplicate** – the same file (SHA-256) imported successfully before is refused.
4. **Required columns** (master data) – both sheets, every required column present (not twice), at least one day /
   week / month column. The rejection message **starts with the missing required column(s)** and says that day /
   week / month columns are never the reason; the report shows each sheet's required columns (✓ / ✕ with the
   similar column of the file) and the two template sections.
5. **Structure** – what the importer needs to read the sheet (e.g. at least one daily value for the data date).
6. **Rows** – each finding **with its Excel row number** (file-level findings show "—"):
   * *critical* – the row is rejected (no GP code / circle; a duplicate GP code – the later row, both rows named);
   * *warning* – the row is kept, the value is left empty (invalid date / number, availability outside 0–100 %,
     a duplicate Block Code – the later row is skipped, both rows named …);
   * *info* – for information (e.g. OLT location missing).

The report also shows, per sheet: **required OK**, **optional present / absent**, **not used** columns, and the
**periods found** (days, weeks, months), their **gaps**, and the weeks / months **kept from earlier uploads**.

Data-quality rules: **blank / NA is never 0** (not reported – excluded from averages and sums; a file without the
optional BSNL / BBNL Live KM column shows NA, not 0 km); only a written 0 is 0. Values are kept as written (trimmed),
never re-mapped silently. The file's own **O&M key numbers** are cross-checked against the rows (warning only).
The browser filters the file type and size, but the backend checks everything again.

## Where files are stored

```
DATA_DIR/staging/   <token>.<ext> + <token>.json   checked uploads waiting for "Confirm import"
                                                    (deleted on cancel, on a failed check and after STAGING_TTL_MINUTES)
DATA_DIR/uploads/   <UTC timestamp>-<sha256[:16]>.<ext>   confirmed uploads (atomic move from staging)
DATA_DIR/raw/       files imported by the CLI / first start
```

The import parses the confirmed file, writes its rows, merges the period history and switches the active dataset
**in one transaction** (a failed import never replaces the active data). The newest `KEEP_DATASETS` (3) successful
imports are kept; older rows and files are pruned (the history tables are not tied to a dataset). One import runs
at a time.

## Settings (environment variables)

`DATA_DIR`, `DATABASE_URL`, `UPLOAD_MAX_MB` (60), `STAGING_TTL_MINUTES` (60), `ZIP_MAX_UNCOMPRESSED_MB` (1024),
`ZIP_MAX_RATIO` (200), `KEEP_DATASETS` (3), `PERIOD_HISTORY_MONTHS` (6).

## API

| Endpoint | |
|---|---|
| `POST /api/v1/ingestion/preview` (form: `file`, `kind` = master \| escalation) | step 1 – stage + validation report (`canImport`, `stage`, `error`, `columnCheck`, `periods`, `counts`, `facts`, `crossCheck`, `issues` with row numbers, `token`) |
| `POST /api/v1/ingestion/confirm` `{token}` | step 2 – import the staged file (202) |
| `DELETE /api/v1/ingestion/preview/{token}` | cancel – delete the staged file |
| `POST /api/v1/ingestion/upload` (form: `file`, optional `kind`) | one-step upload (scripts) – same checks |
| `GET /api/v1/ingestion/template/{gp\|block\|master}.xlsx` | templates (admin) |
| `GET/PATCH /api/v1/field-team/sheet`, `POST …/sheet/replace`, `GET …/sheet/edits`, `GET …/sheet/export.xlsx` | Escalation Sheet |

Tests: `backend/tests/test_template_validation.py` (column buckets, periods, history), `test_upload_pipeline.py`,
`test_escalation_sheet.py`.
